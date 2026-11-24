// SpyglassSetup.cs: the entry point of SpyglassSetup.exe, the helper the MSI package runs for the
// steps Windows Installer cannot do: stopping a running Spyglass, removing the old Inno-installed
// copy, building the Python environment with uv and removing it again.
//
//   SpyglassSetup.exe <prepare|environment|uninstall|remove-environment> --install-dir <dir> [--ui <n>]
//
// Exit codes: 0 done, 1 setup must stop, 2 bad command line. installer\build_setup_helper.ps1
// compiles it with the C# compiler that comes with the .NET Framework 4.x.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;

internal static class SpyglassSetup
{
    private const int Done = 0;
    private const int MustStop = 1;
    private const int BadCommandLine = 2;
    private const string Usage = "Usage: SpyglassSetup.exe <prepare|environment|uninstall|remove-environment> "
        + "--install-dir <folder> [--ui <MSI UILevel number>]";

    /// <summary>Run the command named on the command line and return the exit code.</summary>
    private static int Main()
    {
        List<string> arguments = Tokens(Environment.CommandLine);
        arguments.RemoveAt(0);
        string command, installDir;
        int ui;
        if (!Parse(arguments, out command, out installDir, out ui))
        {
            Console.Error.WriteLine(Usage);
            return BadCommandLine;
        }
        SetupLog log = new SetupLog();
        SetupMessages messages = new SetupMessages(log, ui);
        log.Header(Version(), command);
        try
        {
            return Run(command, installDir, log, messages);
        }
        catch (Exception problem)
        {
            // Setup must end with a clear code and a log line, never a .NET crash dialog. Removing
            // the environment is clean-up, which never fails setup.
            log.Line("Unexpected error: " + problem);
            return command == "remove-environment" ? Done : MustStop;
        }
    }

    /// <summary>Carry out one command.</summary>
    private static int Run(string command, string dir, SetupLog log, SetupMessages messages)
    {
        ProgramRunner runner = new ProgramRunner(log);
        SpyglassStopper stopper = new SpyglassStopper(log, messages);
        EnvironmentSteps steps = new EnvironmentSteps(log, runner);
        switch (command)
        {
            case "prepare":
                if (!stopper.StopAndCheckFree(log.ReadPort(), dir, true))
                {
                    return MustStop;
                }
                if (!new OldInstall(log, runner).Remove())
                {
                    messages.Error(SetupMessages.OldInstallStays());
                    return MustStop;
                }
                return Done;
            case "environment":
                if (!steps.InstallEnvironment(dir))
                {
                    messages.Error(SetupMessages.EnvironmentFailed(log.LogPath));
                    return MustStop;
                }
                steps.RunPythonStep(dir, "install");
                return Done;
            case "uninstall":
                if (!stopper.StopAndCheckFree(log.ReadPort(), dir, false))
                {
                    return MustStop;
                }
                if (EnvironmentSteps.HasPython(dir))
                {
                    steps.RunPythonStep(dir, "uninstall");
                }
                // Python removes it too; this covers an environment that is broken or gone.
                StartupEntry.RemoveIfOurs(dir, log);
                steps.RemoveEnvironment(dir);
                return Done;
            default:
                // remove-environment is the rollback of environment.
                steps.RemoveNewEnvironment(dir);
                return Done;
        }
    }

    /// <summary>
    /// Read the command, --install-dir and --ui. Returns false for anything else: no command, an
    /// unknown command or option, a missing value, or a --ui that is not a number.
    /// </summary>
    private static bool Parse(List<string> arguments, out string command, out string installDir, out int ui)
    {
        command = null;
        installDir = null;
        ui = SetupMessages.UiNotGiven;
        for (int i = 0; i < arguments.Count; i++)
        {
            string argument = arguments[i];
            if (argument == "--install-dir" || argument == "--ui")
            {
                if (i + 1 >= arguments.Count)
                {
                    return false;
                }
                string value = arguments[++i];
                if (argument == "--install-dir")
                {
                    // The package passes "dir\." so that no backslash stands before the closing
                    // quote; a folder passed as "dir\" keeps its backslash. Both become the plain
                    // full path, without a trailing backslash: the code adds its own.
                    try
                    {
                        installDir = Path.GetFullPath(value).TrimEnd('\\');
                    }
                    catch (Exception)
                    {
                        return false;
                    }
                }
                else if (!int.TryParse(value, out ui) || ui < 0)
                {
                    return false;
                }
            }
            else if (command == null && !argument.StartsWith("--"))
            {
                command = argument;
            }
            else
            {
                return false;
            }
        }
        bool known = command == "prepare" || command == "environment" || command == "uninstall"
            || command == "remove-environment";
        return known && !string.IsNullOrEmpty(installDir);
    }

    /// <summary>
    /// Split a command line into its words. Quotes group words and are dropped; a backslash is always
    /// an ordinary character. That differs from the usual rule on purpose: Windows Installer passes
    /// a folder as "C:\Folder\" with its trailing backslash, which the usual rule reads as an escaped
    /// quote and then swallows the rest of the line.
    /// </summary>
    private static List<string> Tokens(string commandLine)
    {
        List<string> words = new List<string>();
        StringBuilder word = new StringBuilder();
        bool quoted = false, inWord = false;
        foreach (char c in commandLine)
        {
            if (c == '"')
            {
                quoted = !quoted;
                inWord = true;
            }
            else if (char.IsWhiteSpace(c) && !quoted)
            {
                if (inWord)
                {
                    words.Add(word.ToString());
                    word.Length = 0;
                    inWord = false;
                }
            }
            else
            {
                word.Append(c);
                inWord = true;
            }
        }
        if (inWord)
        {
            words.Add(word.ToString());
        }
        return words;
    }

    /// <summary>The release version from the program's own file version details.</summary>
    private static string Version()
    {
        return FileVersionInfo.GetVersionInfo(Assembly.GetExecutingAssembly().Location).ProductVersion;
    }
}
