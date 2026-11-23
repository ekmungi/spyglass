// Spyglass.exe: the program at the root of the install folder that the Start-menu entry, the
// start-up entry and the installer's "Open Spyglass now" all start. It runs the desktop app with
// the install folder's own windowless Python, passes its arguments on unchanged and waits until the
// app ends, so Windows shows Spyglass with the Python processes under it. installer\build_launcher.ps1
// compiles it with the C# compiler that comes with the .NET Framework 4.x.
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class SpyglassLauncher
{
    // Where the installer's uv puts the windowless interpreter, relative to the install folder.
    private const string PythonRelative = @".venv\Scripts\pythonw.exe";
    // The desktop app's entry point: the tray, the service and the browser window.
    private const string AppModule = "-m spyglass_service.desktop";
    // Exit code when the app could not be started at all (Python missing or refused to start).
    private const int CannotStart = 2;
    // Set by the automated tests, which have no one to click a message box away.
    private const string NoDialogVariable = "SPYGLASS_LAUNCHER_NO_DIALOG";

    /// <summary>Start the desktop app, wait for it and return its exit code.</summary>
    [STAThread]
    private static int Main()
    {
        string folder = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        string python = Path.Combine(folder, PythonRelative);
        if (!File.Exists(python))
        {
            return Fail(python);
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
    private static int Fail(string python)
    {
        string text = "Spyglass cannot start, because this file is missing or cannot be run:\n\n"
            + python
            + "\n\nRun the Spyglass installer again to repair Spyglass. Your data and settings are kept.";
        if (Environment.GetEnvironmentVariable(NoDialogVariable) == "1")
        {
            Console.Error.WriteLine(text);
        }
        else
        {
            MessageBox.Show(text, "Spyglass", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        return CannotStart;
    }
}
