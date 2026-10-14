# Parse a TMDL semantic-model folder with the TMDL serializer that ships with
# Power BI Desktop (Microsoft.PowerBI.Tabular.dll) and print what was loaded.
# Exit code 1 on any parse error. Nothing is written.
# Usage: powershell -File dashboard/tools/check_tmdl.ps1 <path-to-SemanticModel\definition>
param([Parameter(Mandatory = $true)][string]$Folder,
      [string]$Bin = "C:\Program Files\Microsoft Power BI Desktop\bin")

$ErrorActionPreference = "Stop"
$code = @"
using System;
using System.IO;
using System.Reflection;
using System.Text;
using System.Collections;

public static class TmdlCheck {
    static string bin;
    static Assembly Resolve(object s, ResolveEventArgs e) {
        string n = new AssemblyName(e.Name).Name;
        string p = Path.Combine(bin, n + ".dll");
        return File.Exists(p) ? Assembly.LoadFrom(p) : null;
    }
    static object Get(object o, string prop) { return o.GetType().GetProperty(prop).GetValue(o, null); }
    public static string Run(string binDir, string folder) {
        bin = binDir;
        AppDomain.CurrentDomain.AssemblyResolve += Resolve;
        Assembly asm = Assembly.LoadFrom(Path.Combine(bin, "Microsoft.PowerBI.Tabular.dll"));
        Type ser = asm.GetType("Microsoft.AnalysisServices.Tabular.TmdlSerializer");
        object db;
        try {
            db = ser.GetMethod("DeserializeDatabaseFromFolder", new Type[] { typeof(string) }).Invoke(null, new object[] { folder });
        } catch (Exception ex) {
            while (ex.InnerException != null) ex = ex.InnerException;
            return "TMDL PARSE ERROR: " + ex.GetType().Name + ": " + ex.Message;
        }
        StringBuilder sb = new StringBuilder();
        sb.AppendLine("compatibilityLevel: " + Get(db, "CompatibilityLevel"));
        object model = Get(db, "Model");
        foreach (object t in (IEnumerable)Get(model, "Tables")) {
            int cols = 0;
            foreach (object c in (IEnumerable)Get(t, "Columns")) if (Get(c, "Type").ToString() != "RowNumber") cols++;
            int meas = 0; foreach (object x in (IEnumerable)Get(t, "Measures")) meas++;
            int parts = 0; foreach (object x in (IEnumerable)Get(t, "Partitions")) parts++;
            sb.AppendLine(string.Format("table {0}: {1} columns, {2} measures, {3} partitions", Get(t, "Name"), cols, meas, parts));
        }
        foreach (object r in (IEnumerable)Get(model, "Relationships")) {
            sb.AppendLine(string.Format("relationship {0}[{1}] -> {2}[{3}] cross={4} active={5}",
                Get(Get(r, "FromTable"), "Name"), Get(Get(r, "FromColumn"), "Name"),
                Get(Get(r, "ToTable"), "Name"), Get(Get(r, "ToColumn"), "Name"),
                Get(r, "CrossFilteringBehavior"), Get(r, "IsActive")));
        }
        foreach (object x in (IEnumerable)Get(model, "Expressions")) sb.AppendLine("expression " + Get(x, "Name"));
        foreach (object a in (IEnumerable)Get(model, "Annotations")) {
            string n = (string)Get(a, "Name");
            if (n.StartsWith("__PBI")) sb.AppendLine("annotation " + n + " = " + Get(a, "Value"));
        }
        return sb.ToString();
    }
}
"@
Add-Type -TypeDefinition $code -Language CSharp
$out = [TmdlCheck]::Run($Bin, (Resolve-Path $Folder).Path)
Write-Output $out
if ($out.StartsWith("TMDL PARSE ERROR")) { exit 1 } else { exit 0 }
