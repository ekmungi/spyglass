// SpyglassStopper.cs: stops a running Spyglass before Windows Installer replaces or removes its
// files, and tells whether any program still runs from the install folder. A Spyglass is stopped only
// when the desktop app started it (its health answer says so); a developer copy, an older version or
// any other program on the port is left alone, as the Inno Setup installer did.
using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

internal sealed class SpyglassStopper
{
    // How long one local request may take; a busy service still answers its health check in this.
    private const int RequestTimeoutMs = 2000;
    // How long a stopped Spyglass gets to free its port and end its processes.
    private const int StopWaitMs = 15000;
    private const int PollMs = 250;
    // OpenProcess right that is enough to ask for a process's image path, even for a 64-bit
    // process or one that belongs to another session of the same user.
    private const uint ProcessQueryLimitedInformation = 0x1000;

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint access, bool inheritHandle, int processId);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool QueryFullProcessImageNameW(IntPtr process, uint flags, StringBuilder name, ref int size);

    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(IntPtr handle);

    private readonly SetupLog log;
    private readonly SetupMessages messages;

    public SpyglassStopper(SetupLog log, SetupMessages messages)
    {
        this.log = log;
        this.messages = messages;
    }

    /// <summary>
    /// Stop the Spyglass on `port` when, and only when, the desktop app started it. A Spyglass that
    /// is not the app's is left running, with an information message when `tellUser` is set.
    /// </summary>
    public void StopDesktopSpyglass(int port, string installFolder, bool tellUser)
    {
        string body;
        if (Request("GET", port, "/api/health", out body) != 200)
        {
            log.Line("Nothing answered on port " + port + ".");
            return;
        }
        string compact = Compact(body);
        if (!compact.Contains("\"status\":") || !compact.Contains("\"version\":"))
        {
            log.Line("Another program answers on port " + port + "; it was left alone.");
            return;
        }
        if (!compact.Contains("\"started_by\":\"desktop\""))
        {
            log.Line("A Spyglass that the app did not start runs on port " + port + "; it was left running.");
            if (tellUser)
            {
                messages.Info(SetupMessages.NotStartedByApp(port));
            }
            return;
        }
        log.Line("Asking the Spyglass app on port " + port + " to stop.");
        Request("POST", port, "/api/shutdown", out body);
        WaitUntilStopped(port, installFolder);
    }

    /// <summary>Wait until the port is free and nothing runs from the install folder, at most 15 seconds.</summary>
    private void WaitUntilStopped(int port, string installFolder)
    {
        Stopwatch waited = Stopwatch.StartNew();
        string body;
        do
        {
            if (Request("GET", port, "/api/health", out body) == 0 && ProgramsRunningFrom(installFolder).Length == 0)
            {
                log.Line("It stopped after " + waited.ElapsedMilliseconds + " ms.");
                return;
            }
            Thread.Sleep(PollMs);
        }
        while (waited.ElapsedMilliseconds < StopWaitMs);
        log.Line("It was still running after 15 seconds; setup went on.");
    }

    /// <summary>
    /// One request to the local service, with no proxy. Returns the HTTP status, or 0 when nothing
    /// answered in time. `body` receives the answer text, empty when there is none.
    /// </summary>
    private static int Request(string method, int port, string path, out string body)
    {
        body = "";
        try
        {
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + port + path);
            request.Method = method;
            // No proxy may see or answer a local address.
            request.Proxy = null;
            request.Timeout = RequestTimeoutMs;
            request.ReadWriteTimeout = RequestTimeoutMs;
            request.KeepAlive = false;
            request.ServicePoint.Expect100Continue = false;
            if (method == "POST")
            {
                request.ContentLength = 0;
            }
            using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
            {
                body = ReadAll(response);
                return (int)response.StatusCode;
            }
        }
        catch (WebException problem)
        {
            // An HTTP error status still means something answered; no response means nothing did.
            HttpWebResponse response = problem.Response as HttpWebResponse;
            if (response == null)
            {
                return 0;
            }
            using (response)
            {
                body = ReadAll(response);
                return (int)response.StatusCode;
            }
        }
        catch (IOException)
        {
            // The connection broke while the answer was read: treat it as no answer.
            return 0;
        }
    }

    /// <summary>The text of a response, or an empty string when it cannot be read.</summary>
    private static string ReadAll(HttpWebResponse response)
    {
        try
        {
            using (StreamReader reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
            {
                return reader.ReadToEnd();
            }
        }
        catch (IOException)
        {
            return "";
        }
        catch (WebException)
        {
            return "";
        }
    }

    /// <summary>The text without spaces, tabs and line breaks, so JSON can be matched whatever its layout.</summary>
    private static string Compact(string text)
    {
        return text.Replace(" ", "").Replace("\t", "").Replace("\r", "").Replace("\n", "");
    }

    /// <summary>
    /// The full image paths of the running programs that were started from inside `folder`. It
    /// compares the whole path (with a trailing backslash on the folder) without regard to case.
    /// Setup's own process and processes that cannot be opened are skipped.
    /// </summary>
    public string[] ProgramsRunningFrom(string folder)
    {
        string prefix = Path.GetFullPath(folder).TrimEnd('\\') + "\\";
        int self = Process.GetCurrentProcess().Id;
        System.Collections.Generic.List<string> found = new System.Collections.Generic.List<string>();
        foreach (Process process in Process.GetProcesses())
        {
            using (process)
            {
                if (process.Id == self)
                {
                    continue;
                }
                string image = ImagePath(process.Id);
                if (image != null && image.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                {
                    found.Add(image);
                }
            }
        }
        return found.ToArray();
    }

    /// <summary>The path of a process's program file, or null when Windows will not tell.</summary>
    private static string ImagePath(int processId)
    {
        IntPtr handle = OpenProcess(ProcessQueryLimitedInformation, false, processId);
        if (handle == IntPtr.Zero)
        {
            return null;
        }
        try
        {
            StringBuilder name = new StringBuilder(1024);
            int size = name.Capacity;
            return QueryFullProcessImageNameW(handle, 0, name, ref size) ? name.ToString() : null;
        }
        finally
        {
            CloseHandle(handle);
        }
    }

    /// <summary>
    /// Stop the desktop-started Spyglass, then report whether a program still runs from the install
    /// folder. When one does, the user is told to quit it and false is returned.
    /// </summary>
    public bool StopAndCheckFree(int port, string installFolder, bool tellUser)
    {
        StopDesktopSpyglass(port, installFolder, tellUser);
        string[] running = ProgramsRunningFrom(installFolder);
        if (running.Length == 0)
        {
            return true;
        }
        foreach (string image in running)
        {
            log.Line("Still running from the install folder: " + image);
        }
        messages.Error(SetupMessages.StillRunning(installFolder));
        return false;
    }
}
