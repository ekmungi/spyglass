// SetupMessages.cs: the texts SpyglassSetup.exe shows the user, and how they are shown. Every
// message goes to the log. It also opens a topmost message box, but only when Windows Installer runs
// with its reduced or full interface (or when no level was given); a silent install shows nothing.
// SPYGLASS_LAUNCHER_NO_DIALOG=1, the test switch the launcher also honours, writes to stderr instead.
using System;
using System.Runtime.InteropServices;

internal sealed class SetupMessages
{
    private const string NoDialogVariable = "SPYGLASS_LAUNCHER_NO_DIALOG";
    private const string Caption = "Spyglass Setup";

    // MessageBoxW styles: an icon, one OK button, and the two flags that bring the box to the front
    // and keep it above other windows. Setup owns no window, so without them the box may open behind
    // whatever is on screen.
    private const uint MB_ICONERROR = 0x10;
    private const uint MB_ICONINFORMATION = 0x40;
    private const uint MB_SETFOREGROUND = 0x10000;
    private const uint MB_TOPMOST = 0x40000;

    // The MSI UILevel values that allow a message box (reduced and full); -1 means "not given".
    private const int UiReduced = 4;
    private const int UiFull = 5;
    public const int UiNotGiven = -1;

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBoxW(IntPtr owner, string text, string caption, uint type);

    private readonly SetupLog log;
    private readonly int ui;

    public SetupMessages(SetupLog log, int ui)
    {
        this.log = log;
        this.ui = ui;
    }

    /// <summary>Report a problem that stops setup.</summary>
    public void Error(string text)
    {
        Show(text, MB_ICONERROR);
    }

    /// <summary>Report something the user should know that does not stop setup.</summary>
    public void Info(string text)
    {
        Show(text, MB_ICONINFORMATION);
    }

    /// <summary>Log the text, then show it the way the settings allow.</summary>
    private void Show(string text, uint icon)
    {
        log.Line("Message: " + text.Replace("\r\n", " ").Replace("\n", " "));
        if (Environment.GetEnvironmentVariable(NoDialogVariable) == "1")
        {
            Console.Error.WriteLine(text);
        }
        else if (ui == UiNotGiven || ui == UiReduced || ui == UiFull)
        {
            MessageBoxW(IntPtr.Zero, text, Caption, icon | MB_SETFOREGROUND | MB_TOPMOST);
        }
    }

    /// <summary>Shown when a program from the install folder still runs after Spyglass was asked to stop.</summary>
    public static string StillRunning(string folder)
    {
        return "Spyglass is still running from " + folder + ", so Setup cannot replace it. Quit Spyglass "
            + "from its icon in the notification area (Windows may hide it behind the ^ arrow), close any "
            + "Spyglass message that is open, then run Setup again.";
    }

    /// <summary>Shown when a Spyglass that the desktop app did not start answers on the port.</summary>
    public static string NotStartedByApp(int port)
    {
        return "A Spyglass that was not started by the Spyglass app is running on port " + port
            + ", for example from a command line, a script or the Obsidian plugin.\r\n\r\n"
            + "Setup leaves it running. Stop it before you open the installed Spyglass, because only one "
            + "Spyglass can use the port.";
    }

    /// <summary>Shown when the Inno-installed Spyglass of 0.41.1 and older could not be removed.</summary>
    public static string OldInstallStays()
    {
        return "Setup could not remove the earlier Spyglass, which its old installer put on this PC. "
            + "Remove Spyglass in Settings > Apps > Installed apps, then run this setup again. "
            + "Your data folder and settings are kept either way.";
    }

    /// <summary>Shown when uv could not build Python and the libraries.</summary>
    public static string EnvironmentFailed(string logPath)
    {
        return "Setup could not prepare Python and the libraries Spyglass needs. The details are in " + logPath + ".";
    }
}
