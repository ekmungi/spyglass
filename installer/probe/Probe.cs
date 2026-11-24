// A throwaway program for one test: which kind of installer makes Windows show a new app in the
// Start menu straight away. Started from its Start-menu entry, it only shows its own name, which
// is the name of the program file.
using System;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;

internal static class Probe
{
    // An information icon, brought to the front.
    private const uint Style = 0x40 | 0x10000 | 0x40000;

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBoxW(IntPtr owner, string text, string caption, uint type);

    /// <summary>Show that this probe was started from its shortcut.</summary>
    private static void Main()
    {
        string name = Path.GetFileNameWithoutExtension(Assembly.GetEntryAssembly().Location);
        MessageBoxW(IntPtr.Zero,
            name + " was started from its Start-menu entry. Uninstall it from Settings > Installed apps "
            + "when the test is done.",
            name, Style);
    }
}
