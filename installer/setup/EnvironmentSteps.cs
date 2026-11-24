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
        return code == 0;
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
        runner.Run(start, PythonStepTimeoutMs, true);
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
