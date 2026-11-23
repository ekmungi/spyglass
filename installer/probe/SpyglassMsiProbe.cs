// A throwaway program for one test: it is installed by a small Windows Installer (.msi) package to
// check whether Windows lists an MSI-installed app in the Start menu and in Settings > Installed apps.
// Started from its Start-menu entry, it only shows a message.
using System;
using System.Runtime.InteropServices;

internal static class SpyglassMsiProbe
{
    // An information icon, brought to the front.
    private const uint Style = 0x40 | 0x10000 | 0x40000;

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBoxW(IntPtr owner, string text, string caption, uint type);

    /// <summary>Show that the probe was installed and started from its shortcut.</summary>
    private static void Main()
    {
        MessageBoxW(IntPtr.Zero,
            "The Spyglass MSI probe was installed with Windows Installer and started from its shortcut. "
            + "Uninstall it from Settings > Installed apps when the test is done.",
            "Spyglass MSI Probe", Style);
    }
}
