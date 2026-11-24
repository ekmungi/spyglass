// StartupEntry.cs: removes the "Start with Windows" entry on uninstall when it starts this install.
// Spyglass's own uninstall step removes it too, but that step needs Spyglass's Python; when the
// environment is broken or gone, the entry would otherwise be left pointing at a deleted program.
using System;
using Microsoft.Win32;

internal static class StartupEntry
{
    // The per-user key Windows reads at sign-in, and the value name Spyglass uses there.
    private const string DefaultKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string ValueName = "Spyglass";
    // Tests name a scratch key here instead (still under HKCU).
    private const string KeyVariable = "SPYGLASS_SETUP_RUN_KEY";

    /// <summary>Delete the entry when its command starts a program inside `dir`; log what was done.</summary>
    public static void RemoveIfOurs(string dir, SetupLog log)
    {
        string path = Environment.GetEnvironmentVariable(KeyVariable);
        try
        {
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(string.IsNullOrEmpty(path) ? DefaultKey : path, true))
            {
                string command = key == null ? null : key.GetValue(ValueName) as string;
                if (command == null)
                {
                    return;
                }
                if (command.IndexOf(dir.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase) < 0)
                {
                    log.Line("The start-up entry starts another copy of Spyglass; it was left as it is.");
                    return;
                }
                key.DeleteValue(ValueName, false);
                log.Line("Removed the start-up entry of this install.");
            }
        }
        catch (Exception problem)
        {
            // A locked Run key must not stop the uninstall; the log says what was left.
            log.Line("Could not check the start-up entry: " + problem.Message);
        }
    }
}
