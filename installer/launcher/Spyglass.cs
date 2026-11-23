// Spyglass.exe: the program at the root of the install folder that the Start-menu entry, the
// start-up entry and the installer's "Open Spyglass now" all start. It runs the desktop app with
// the install folder's own windowless Python, passes its arguments on unchanged and waits until the
// app ends, so Windows shows Spyglass with the Python processes under it. installer\build_launcher.ps1
// compiles it with the C# compiler that comes with the .NET Framework 4.x.
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

internal static class SpyglassLauncher
{
    // Where the installer's uv puts the windowless interpreter, relative to the install folder.
    private const string PythonRelative = @".venv\Scripts\pythonw.exe";
    // The venv's settings file; its "home" line names the folder of the Python the venv runs on.
    private const string VenvConfigRelative = @".venv\pyvenv.cfg";
    // The desktop app's entry point: the tray, the service and the browser window.
    private const string AppModule = "-m spyglass_service.desktop";
    // Exit code when the app could not be started at all (Python missing or refused to start).
    private const int CannotStart = 2;
    // Set by the automated tests, which have no one to click a message box away.
    private const string NoDialogVariable = "SPYGLASS_LAUNCHER_NO_DIALOG";

    // MessageBoxW style: an error icon and one OK button, brought to the front and kept above other
    // windows. The launcher owns no window, so without the last two flags Windows may open the box
    // behind whatever is on screen, for example at sign-in.
    private const uint MB_ICONERROR = 0x10;
    private const uint MB_SETFOREGROUND = 0x10000;
    private const uint MB_TOPMOST = 0x40000;

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBoxW(IntPtr owner, string text, string caption, uint type);

    /// <summary>Start the desktop app, wait for it and return its exit code.</summary>
    private static int Main()
    {
        string folder = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        string python = Path.Combine(folder, PythonRelative);
        if (!File.Exists(python))
        {
            return Fail(python);
        }
        string basePython = MissingBasePython(Path.Combine(folder, VenvConfigRelative));
        if (basePython != null)
        {
            return Fail(basePython);
        }

        string rest = ArgumentsAfterProgram(Environment.CommandLine);
        ProcessStartInfo start = new ProcessStartInfo(python, rest.Length == 0 ? AppModule : AppModule + " " + rest)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = folder,
        };
        try
        {
            using (Process app = Process.Start(start))
            {
                app.WaitForExit();
                return app.ExitCode;
            }
        }
        catch (Win32Exception)
        {
            // The file is there but Windows would not run it (damaged, blocked or the wrong kind).
            return Fail(python);
        }
    }

    /// <summary>
    /// The base interpreter the venv's pyvenv.cfg names, when that file is gone; null when it is
    /// there or the venv has no pyvenv.cfg. The venv's own pythonw.exe only hands over to this one,
    /// and when it is missing it fails with a message that does not say what to do.
    /// </summary>
    private static string MissingBasePython(string venvConfig)
    {
        if (!File.Exists(venvConfig))
        {
            return null;
        }
        string[] lines;
        try
        {
            lines = File.ReadAllLines(venvConfig);
        }
        catch (Exception)
        {
            // An unreadable file is left to Python, which reports its own problem; the launcher
            // must never end in a .NET crash dialog.
            return null;
        }
        foreach (string line in lines)
        {
            int equals = line.IndexOf('=');
            if (equals < 0 || line.Substring(0, equals).Trim() != "home")
            {
                continue;
            }
            string basePython = Path.Combine(line.Substring(equals + 1).Trim(), "pythonw.exe");
            return File.Exists(basePython) ? null : basePython;
        }
        return null;
    }

    /// <summary>
    /// The command line after its first token, the program's own path, exactly as Windows passed
    /// it. Passing the text on instead of rebuilding it from parsed arguments keeps any quoting.
    /// </summary>
    private static string ArgumentsAfterProgram(string commandLine)
    {
        string line = commandLine.TrimStart();
        int end;
        if (line.StartsWith("\""))
        {
            int closing = line.IndexOf('"', 1);
            end = closing < 0 ? line.Length : closing + 1;
        }
        else
        {
            end = line.IndexOfAny(new[] { ' ', '\t' });
            if (end < 0)
            {
                end = line.Length;
            }
        }
        return line.Substring(end).TrimStart();
    }

    /// <summary>Tell the user which file is missing and what to do, then return the failure code.</summary>
    private static int Fail(string missing)
    {
        string text = "Spyglass cannot start, because this file is missing or cannot be run:\n\n"
            + missing
            + "\n\nRun the Spyglass installer again to repair Spyglass. Your data and settings are kept.";
        if (Environment.GetEnvironmentVariable(NoDialogVariable) == "1")
        {
            Console.Error.WriteLine(text);
        }
        else
        {
            MessageBoxW(IntPtr.Zero, text, "Spyglass", MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST);
        }
        return CannotStart;
    }
}
