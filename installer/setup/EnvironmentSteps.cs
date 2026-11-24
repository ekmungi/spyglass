// EnvironmentSteps.cs: builds and removes the Python environment inside the install folder. uv
// installs Python 3.13 and the locked libraries; Spyglass's own Python code then does the
// per-user setup (settings, shortcuts, autostart). Removing the environment is also the rollback of
// a failed install.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Threading;
using Microsoft.Win32;

internal sealed class EnvironmentSteps
{
    // Where the installer's tick boxes are recorded; tests name a scratch key instead (under HKCU).
    private const string FeaturesKeyDefault = @"Software\ekmungi\Spyglass\Features";
    private const string FeaturesKeyVariable = "SPYGLASS_SETUP_FEATURES_KEY";
    // How long the Python setup step may run before Setup stops waiting for it.
    private const int PythonStepTimeoutMs = 15 * 60 * 1000;
    private const string PythonRelative = @".venv\Scripts\pythonw.exe";
    // Written while uv builds an environment that did not exist before, and deleted once it is
    // built. Only then may undoing setup delete the environment: a failed or cancelled Modify or
    // upgrade must keep the Python that already worked.
    public const string NewEnvironmentMarker = ".venv-being-built";

    private readonly SetupLog log;
    private readonly ProgramRunner runner;

    public EnvironmentSteps(SetupLog log, ProgramRunner runner)
    {
        this.log = log;
        this.runner = runner;
    }

    /// <summary>The uv extras for the features the user ticked ("1" in the registry), in a fixed order.</summary>
    private static string ExtraArguments()
    {
        string path = Environment.GetEnvironmentVariable(FeaturesKeyVariable);
        using (RegistryKey key = Registry.CurrentUser.OpenSubKey(string.IsNullOrEmpty(path) ? FeaturesKeyDefault : path))
        {
            string extras = "";
            if (key != null && (key.GetValue("pdf") as string) == "1")
            {
                extras += " --extra pdf";
            }
            if (key != null && (key.GetValue("local-ai") as string) == "1")
            {
                extras += " --extra local-ai";
            }
            return extras;
        }
    }

    /// <summary>
    /// Install Python 3.13 and the locked libraries into the install folder with uv. Returns true
    /// when uv succeeded. The cache is a fresh temp folder that is deleted afterwards.
    /// </summary>
    public bool InstallEnvironment(string dir)
    {
        string marker = Path.Combine(dir, NewEnvironmentMarker);
        if (!Directory.Exists(Path.Combine(dir, ".venv")))
        {
            WriteMarker(marker);
        }
        string cache = Path.Combine(Path.GetTempPath(), "spyglass-uv-" + Guid.NewGuid().ToString("N"));
        ProcessStartInfo start = ProgramRunner.Describe(Path.Combine(dir, "uv.exe"),
            "sync --frozen --no-dev --python 3.13" + ExtraArguments(), dir);
        // UV_MANAGED_PYTHON keeps uv from building the environment on a Python found elsewhere on
        // the PC, which an uninstall of that Python would break. The two INSTALL variables keep uv
        // from adding a python.exe to the user's PATH folder or a Python entry to the registry:
        // nothing may point into the install folder after an uninstall. Copies, not links, so
        // nothing points into the deleted cache. Compiling the libraries here keeps that work out
        // of the first start, which must open the interface within 30 seconds.
        start.EnvironmentVariables["UV_PYTHON_INSTALL_DIR"] = Path.Combine(dir, "python");
        start.EnvironmentVariables["UV_PROJECT_ENVIRONMENT"] = Path.Combine(dir, ".venv");
        start.EnvironmentVariables["UV_LINK_MODE"] = "copy";
        start.EnvironmentVariables["UV_CACHE_DIR"] = cache;
        start.EnvironmentVariables["UV_MANAGED_PYTHON"] = "1";
        start.EnvironmentVariables["UV_PYTHON_INSTALL_BIN"] = "0";
        start.EnvironmentVariables["UV_PYTHON_INSTALL_REGISTRY"] = "0";
        start.EnvironmentVariables["UV_COMPILE_BYTECODE"] = "1";
        int code = runner.Run(start, Timeout.Infinite, true);
        runner.RemoveDeepFolder(cache);
        if (code == 0)
        {
            DeleteMarker(marker);
        }
        return code == 0;
    }

    /// <summary>Note that this run is building a new environment; a failure to write it is logged.</summary>
    private void WriteMarker(string marker)
    {
        try
        {
            File.WriteAllText(marker, "Setup is building Python here. Undoing setup deletes it.");
        }
        catch (Exception problem)
        {
            log.Line("Could not write " + marker + ": " + problem.Message);
        }
    }

    /// <summary>Delete the marker when it exists; a failure is logged.</summary>
    private void DeleteMarker(string marker)
    {
        try
        {
            if (File.Exists(marker))
            {
                File.Delete(marker);
            }
        }
        catch (Exception problem)
        {
            log.Line("Could not delete " + marker + ": " + problem.Message);
        }
    }

    /// <summary>
    /// Undo `environment`: delete the environment only when this setup was building a new one (the
    /// marker is there). An environment that existed before is kept, so a failed or cancelled
    /// Modify or upgrade leaves the Spyglass that worked.
    /// </summary>
    public void RemoveNewEnvironment(string dir)
    {
        if (!File.Exists(Path.Combine(dir, NewEnvironmentMarker)))
        {
            log.Line("Kept the Python environment that was there before this setup.");
            return;
        }
        RemoveEnvironment(dir);
    }

    /// <summary>
    /// Run one step of Spyglass's own Python setup code ("install" or "uninstall") with the
    /// environment's windowless Python. It writes its own lines to install.log; its failure is
    /// logged and never fails setup, because the files are already in place or about to go.
    /// </summary>
    public void RunPythonStep(string dir, string step)
    {
        string python = Path.Combine(dir, PythonRelative);
        ProcessStartInfo start = ProgramRunner.Describe(python,
            "-I -X utf8 -m spyglass_service.desktop.setup_steps " + step + " --install-dir \"" + dir + "\"", dir);
        // The uv settings must not reach Spyglass's own code: they exist only while uv runs.
        List<string> inherited = new List<string>();
        foreach (string name in start.EnvironmentVariables.Keys)
        {
            if (name.StartsWith("UV_", StringComparison.OrdinalIgnoreCase))
            {
                inherited.Add(name);
            }
        }
        foreach (string name in inherited)
        {
            start.EnvironmentVariables.Remove(name);
        }
        // Windows Installer may start setup steps with another environment than the user's. These
        // folders come from the signed-in account itself, and Spyglass's code finds Claude Code
        // and uv's tool folder through them.
        SetFolder(start, "USERPROFILE", Environment.SpecialFolder.UserProfile);
        SetFolder(start, "APPDATA", Environment.SpecialFolder.ApplicationData);
        SetFolder(start, "LOCALAPPDATA", Environment.SpecialFolder.LocalApplicationData);
        runner.Run(start, PythonStepTimeoutMs, true);
    }

    /// <summary>
    /// Set one environment variable to the signed-in user's folder. Windows keeps the session's own
    /// values under HKCU\Volatile Environment, which a different process environment cannot change;
    /// GetFolderPath, which follows the process environment, is the fallback.
    /// </summary>
    private static void SetFolder(ProcessStartInfo start, string name, Environment.SpecialFolder folder)
    {
        string path = null;
        try
        {
            using (RegistryKey session = Registry.CurrentUser.OpenSubKey("Volatile Environment"))
            {
                path = session == null ? null : session.GetValue(name) as string;
            }
        }
        catch (Exception)
        {
            path = null;
        }
        if (string.IsNullOrEmpty(path))
        {
            path = Environment.GetFolderPath(folder);
        }
        if (!string.IsNullOrEmpty(path))
        {
            start.EnvironmentVariables[name] = path;
        }
    }

    /// <summary>Whether the install folder holds the environment's Python.</summary>
    public static bool HasPython(string dir)
    {
        return File.Exists(Path.Combine(dir, PythonRelative));
    }

    /// <summary>Delete .venv, python and every __pycache__ folder under src. Missing folders are fine.</summary>
    public void RemoveEnvironment(string dir)
    {
        runner.RemoveDeepFolder(Path.Combine(dir, ".venv"));
        runner.RemoveDeepFolder(Path.Combine(dir, "python"));
        RemoveCaches(Path.Combine(dir, "src"));
        DeleteMarker(Path.Combine(dir, NewEnvironmentMarker));
    }

    /// <summary>Delete the __pycache__ folders below `folder`, which Python made after the files were installed.</summary>
    private void RemoveCaches(string folder)
    {
        string[] children;
        try
        {
            children = Directory.Exists(folder) ? Directory.GetDirectories(folder) : new string[0];
        }
        catch (IOException problem)
        {
            log.Line("Could not look inside " + folder + ": " + problem.Message);
            return;
        }
        catch (UnauthorizedAccessException problem)
        {
            log.Line("Could not look inside " + folder + ": " + problem.Message);
            return;
        }
        foreach (string child in children)
        {
            if (string.Equals(Path.GetFileName(child), "__pycache__", StringComparison.OrdinalIgnoreCase))
            {
                runner.RemoveDeepFolder(child);
            }
            else
            {
                RemoveCaches(child);
            }
        }
    }
}
