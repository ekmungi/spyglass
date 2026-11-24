// ProgramRunner.cs: starts a program without a window, waits for it and writes what it printed and
// its exit code to the log. Everything SpyglassSetup.exe runs (uv, Python, the old uninstaller, cmd)
// goes through here, so the log always shows the command line and the result of each step.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;

internal sealed class ProgramRunner
{
    // Returned when the program could not be started at all.
    public const int CouldNotStart = -1;
    // Returned when the program ran past its time limit and was stopped.
    public const int TimedOut = -2;
    // How long to wait for the output readers after the program ended. A program that left a child
    // behind holding the output pipe would otherwise keep Setup waiting for ever.
    private const int ReaderGraceMs = 5000;

    private readonly SetupLog log;

    public ProgramRunner(SetupLog log)
    {
        this.log = log;
    }

    /// <summary>A start description for `exe` with `arguments` in `workDir` (the caller may add variables).</summary>
    public static ProcessStartInfo Describe(string exe, string arguments, string workDir)
    {
        ProcessStartInfo start = new ProcessStartInfo(exe, arguments);
        if (!string.IsNullOrEmpty(workDir))
        {
            start.WorkingDirectory = workDir;
        }
        return start;
    }

    /// <summary>
    /// Run the program and return its exit code, CouldNotStart or TimedOut. With `capture` its output
    /// lines are appended to the log as they arrive; without it the program inherits Setup's own
    /// standard handles, which suits a program that restarts itself and leaves a child holding them.
    /// </summary>
    public int Run(ProcessStartInfo start, int timeoutMs, bool capture)
    {
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        if (capture)
        {
            start.RedirectStandardOutput = true;
            start.RedirectStandardError = true;
            start.StandardOutputEncoding = Encoding.UTF8;
            start.StandardErrorEncoding = Encoding.UTF8;
        }
        log.Line("> \"" + start.FileName + "\" " + start.Arguments);
        Process program;
        try
        {
            program = Process.Start(start);
        }
        catch (Win32Exception problem)
        {
            log.Line("Could not start it: " + problem.Message);
            return CouldNotStart;
        }
        using (program)
        {
            List<Thread> readers = new List<Thread>();
            if (capture)
            {
                readers.Add(Pump(program.StandardOutput));
                readers.Add(Pump(program.StandardError));
            }
            bool finished = program.WaitForExit(timeoutMs);
            if (!finished)
            {
                log.Line("It was still running after " + (timeoutMs / 1000) + " seconds, so Setup stopped it.");
                try
                {
                    program.Kill();
                }
                catch (InvalidOperationException)
                {
                    // It ended on its own between the wait and the kill.
                }
                program.WaitForExit();
            }
            foreach (Thread reader in readers)
            {
                reader.Join(ReaderGraceMs);
            }
            if (!finished)
            {
                return TimedOut;
            }
            log.Line("Exit code " + program.ExitCode + ".");
            return program.ExitCode;
        }
    }

    /// <summary>Copy a program's output to the log, line by line, on its own thread.</summary>
    private Thread Pump(StreamReader source)
    {
        Thread thread = new Thread(delegate ()
        {
            string line;
            while ((line = source.ReadLine()) != null)
            {
                log.Line(line);
            }
        });
        thread.IsBackground = true;
        thread.Start();
        return thread;
    }

    /// <summary>
    /// Delete a folder, and everything in it, with cmd's rd through a \\?\ path. The deepest files of
    /// a Python environment can pass the old 260-character path limit, which .NET's own delete cannot
    /// handle. A missing folder is fine.
    /// </summary>
    public void RemoveDeepFolder(string folder)
    {
        if (!Directory.Exists(folder))
        {
            return;
        }
        string cmd = Path.Combine(Environment.SystemDirectory, "cmd.exe");
        string full = Path.GetFullPath(folder).TrimEnd('\\');
        Run(Describe(cmd, "/C rd /s /q \"\\\\?\\" + full + "\"", null), Timeout.Infinite, true);
    }
}
