// OldInstall.cs: removes a Spyglass that the earlier Inno Setup installer (0.41.1 and older) put on
// this PC, so the MSI can take its place. The old uninstaller keeps the data folder and desktop.json
// by itself. Inno's uninstaller restarts itself from the temp folder and the first process can end
// at once, so the only reliable sign that it is done is that its uninstall key is gone.
using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using Microsoft.Win32;

internal sealed class OldInstall
{
    // The old installer's uninstall key under HKCU: its application ID plus "_is1".
    private const string DefaultKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\{47FEF1B5-716C-4F96-8B91-F0DFA8A5C7F5}_is1";
    // Tests name a scratch key here instead (still under HKCU).
    private const string KeyOverrideVariable = "SPYGLASS_SETUP_INNO_KEY";
    // Tests set a short wait here, in seconds.
    private const string WaitOverrideVariable = "SPYGLASS_SETUP_WAIT_S";
    // How long to wait for the old install to disappear: a slow disk and antivirus can take a while.
    private const int DefaultWaitSeconds = 120;
    private const int PollMs = 250;
    private const string SilentArguments = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART";

    private readonly SetupLog log;
    private readonly ProgramRunner runner;

    public OldInstall(SetupLog log, ProgramRunner runner)
    {
        this.log = log;
        this.runner = runner;
    }

    private static string KeyPath()
    {
        string path = Environment.GetEnvironmentVariable(KeyOverrideVariable);
        return string.IsNullOrEmpty(path) ? DefaultKey : path;
    }

    /// <summary>The old uninstaller's command text, or null when no old install is registered.</summary>
    private static string UninstallString()
    {
        using (RegistryKey key = Registry.CurrentUser.OpenSubKey(KeyPath()))
        {
            return key == null ? null : (key.GetValue("UninstallString") as string ?? "");
        }
    }

    private static bool KeyExists()
    {
        using (RegistryKey key = Registry.CurrentUser.OpenSubKey(KeyPath()))
        {
            return key != null;
        }
    }

    /// <summary>The program file inside an UninstallString, which is quoted and may carry arguments.</summary>
    public static string ProgramOf(string uninstallString)
    {
        string text = uninstallString.Trim();
        if (text.StartsWith("\""))
        {
            int closing = text.IndexOf('"', 1);
            return closing < 0 ? text.Substring(1) : text.Substring(1, closing - 1);
        }
        if (File.Exists(text))
        {
            return text;
        }
        int space = text.IndexOf(' ');
        return space < 0 ? text : text.Substring(0, space);
    }

    /// <summary>
    /// Remove the old install when there is one. Returns true when none is left (or there never
    /// was one), false when it is still there; the reason is in the log.
    /// </summary>
    public bool Remove()
    {
        string command = UninstallString();
        if (command == null)
        {
            log.Line("No earlier Inno-installed Spyglass is registered.");
            return true;
        }
        string program = ProgramOf(command);
        log.Line("An earlier Spyglass is registered: " + command);
        if (!File.Exists(program))
        {
            log.Line("Its uninstaller is missing: " + program);
            return false;
        }
        // The old uninstaller restarts itself and leaves a child holding any pipe it was given, so
        // it inherits Setup's handles instead of being captured. It gets a time limit, so that one
        // stuck on a question it should not ask stops Setup with a message instead of hanging it.
        int seconds = WaitSeconds();
        int code = runner.Run(ProgramRunner.Describe(program, SilentArguments, Path.GetDirectoryName(program)), seconds * 1000, false);
        if (code == ProgramRunner.CouldNotStart || code == ProgramRunner.TimedOut)
        {
            return false;
        }
        return WaitUntilGone(seconds);
    }

    /// <summary>How long the old uninstaller and its key may take, in seconds.</summary>
    private static int WaitSeconds()
    {
        int seconds;
        if (!int.TryParse(Environment.GetEnvironmentVariable(WaitOverrideVariable), out seconds) || seconds < 1)
        {
            seconds = DefaultWaitSeconds;
        }
        return seconds;
    }

    /// <summary>Wait until the old uninstall key is gone; true when it went, false when the wait ran out.</summary>
    private bool WaitUntilGone(int seconds)
    {
        Stopwatch waited = Stopwatch.StartNew();
        while (KeyExists())
        {
            if (waited.ElapsedMilliseconds >= seconds * 1000L)
            {
                log.Line("The earlier Spyglass was still registered after " + seconds + " seconds.");
                return false;
            }
            Thread.Sleep(PollMs);
        }
        log.Line("The earlier Spyglass was removed.");
        return true;
    }
}
