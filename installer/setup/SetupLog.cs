// SetupLog.cs: where SpyglassSetup.exe writes install.log and finds desktop.json. Both live in the
// per-user Spyglass settings folder, the same place the Python side of setup writes to, so one file
// tells the whole story of an install. The log is appended to, UTF-8 without a byte-order mark.
using System;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;

internal sealed class SetupLog
{
    // The port Spyglass uses when desktop.json does not name a usable one.
    public const int DefaultPort = 7777;
    // Names a scratch desktop.json for test runs; the Python side honours the same variable.
    private const string ConfigOverrideVariable = "SPYGLASS_DESKTOP_CONFIG";

    private static readonly Regex PortPattern = new Regex("\"port\"\\s*:\\s*(\\d+)");
    private static readonly UTF8Encoding Utf8NoBom = new UTF8Encoding(false);

    private readonly object gate = new object();

    public string Folder { get; private set; }
    public string LogPath { get; private set; }
    public string ConfigPath { get; private set; }

    /// <summary>Find the settings folder: the override file's folder, else %LOCALAPPDATA%\Spyglass.</summary>
    public SetupLog()
    {
        string overrideFile = Environment.GetEnvironmentVariable(ConfigOverrideVariable);
        if (!string.IsNullOrEmpty(overrideFile))
        {
            ConfigPath = Path.GetFullPath(overrideFile);
            Folder = Path.GetDirectoryName(ConfigPath);
        }
        else
        {
            Folder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Spyglass");
            ConfigPath = Path.Combine(Folder, "desktop.json");
        }
        LogPath = Path.Combine(Folder, "install.log");
    }

    /// <summary>Append one line to the log. Safe to call from several threads.</summary>
    public void Line(string text)
    {
        lock (gate)
        {
            try
            {
                Directory.CreateDirectory(Folder);
                File.AppendAllText(LogPath, text + Environment.NewLine, Utf8NoBom);
            }
            catch (IOException)
            {
                // A log that cannot be written must not stop the install it describes.
            }
            catch (UnauthorizedAccessException)
            {
                // Same reason: the install goes on without its log.
            }
        }
    }

    /// <summary>Start a command's section with a line naming the program, the command and the time.</summary>
    public void Header(string version, string command)
    {
        Line("--- Spyglass Setup " + version + " " + command + ", " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " ---");
    }

    /// <summary>The port in desktop.json (1 to 65535), or the default when there is none.</summary>
    public int ReadPort()
    {
        try
        {
            Match match = PortPattern.Match(File.ReadAllText(ConfigPath));
            int port;
            if (match.Success && int.TryParse(match.Groups[1].Value, out port) && port >= 1 && port <= 65535)
            {
                return port;
            }
        }
        catch (IOException)
        {
            // No readable settings file: a fresh PC, which uses the default port.
        }
        catch (UnauthorizedAccessException)
        {
            // Same: fall back to the default port.
        }
        return DefaultPort;
    }
}
