# Deploy the TMDL model to a running local Analysis Services engine (msmdsrv.exe from
# Power BI Desktop), run a full refresh (Power Query reads the CSVs) and execute DAX queries.
# Used to test the semantic model without opening Power BI Desktop.
#
# Usage:
#   powershell -File dashboard/tools/run_model.ps1 -Port 50771 `
#       -Folder dashboard\tse_inflation.SemanticModel\definition `
#       -QueryFile queries.dax -OutFile results.tsv
# QueryFile: DAX queries separated by lines containing only "-- next". Output: for each query
# a "## <n>" header, then tab-separated rows (first row = column names), or "ERROR: ...".
param([Parameter(Mandatory = $true)][int]$Port,
      [Parameter(Mandatory = $true)][string]$Folder,
      [Parameter(Mandatory = $true)][string]$QueryFile,
      [Parameter(Mandatory = $true)][string]$OutFile,
      [string]$Database = "tse_inflation_check",
      [string]$Bin = "C:\Program Files\Microsoft Power BI Desktop\bin")

$ErrorActionPreference = "Stop"
$code = @"
using System;
using System.IO;
using System.Reflection;
using System.Text;
using System.Collections;

public static class ModelRunner {
    static string bin;
    static Assembly Resolve(object s, ResolveEventArgs e) {
        string n = new AssemblyName(e.Name).Name;
        string p = Path.Combine(bin, n + ".dll");
        return File.Exists(p) ? Assembly.LoadFrom(p) : null;
    }
    static object Prop(object o, string name) { return o.GetType().GetProperty(name).GetValue(o, null); }
    static void SetProp(object o, string name, object v) { o.GetType().GetProperty(name).SetValue(o, v, null); }
    static object Call(object o, string name, params object[] a) {
        foreach (MethodInfo m in o.GetType().GetMethods())
            if (m.Name == name && m.GetParameters().Length == a.Length) return m.Invoke(o, a);
        throw new MissingMethodException(o.GetType().Name + "." + name);
    }
    static string Inner(Exception ex) { while (ex.InnerException != null) ex = ex.InnerException; return ex.GetType().Name + ": " + ex.Message; }

    public static string Run(string binDir, int port, string folder, string dbName, string queryFile, string outFile) {
        bin = binDir;
        AppDomain.CurrentDomain.AssemblyResolve += Resolve;
        StringBuilder log = new StringBuilder();
        Assembly tab = Assembly.LoadFrom(Path.Combine(bin, "Microsoft.PowerBI.Tabular.dll"));
        Type ser = tab.GetType("Microsoft.AnalysisServices.Tabular.TmdlSerializer");
        object db = ser.GetMethod("DeserializeDatabaseFromFolder", new Type[] { typeof(string) }).Invoke(null, new object[] { folder });
        SetProp(db, "Name", dbName);
        SetProp(db, "ID", dbName);
        object server = Activator.CreateInstance(tab.GetType("Microsoft.AnalysisServices.Tabular.Server"));
        Call(server, "Connect", "Data Source=localhost:" + port);
        object dbs = Prop(server, "Databases");
        object existing = Call(dbs, "FindByName", dbName);
        if (existing != null) Call(existing, "Drop");
        Call(dbs, "Add", db);
        Type updOpt = tab.GetType("Microsoft.AnalysisServices.UpdateOptions") ?? Type.GetType("Microsoft.AnalysisServices.UpdateOptions, Microsoft.PowerBI.Amo");
        if (updOpt == null) {
            foreach (Assembly a in AppDomain.CurrentDomain.GetAssemblies()) { updOpt = a.GetType("Microsoft.AnalysisServices.UpdateOptions"); if (updOpt != null) break; }
        }
        try { Call(db, "Update", Enum.Parse(updOpt, "ExpandFull")); log.AppendLine("deploy: OK"); }
        catch (Exception ex) { log.AppendLine("deploy: FAILED " + Inner(ex)); return log.ToString(); }
        object model = Prop(db, "Model");
        Type refreshType = tab.GetType("Microsoft.AnalysisServices.Tabular.RefreshType");
        try {
            Call(model, "RequestRefresh", Enum.Parse(refreshType, "Full"));
            Call(model, "SaveChanges");
            log.AppendLine("refresh: OK");
        } catch (Exception ex) { log.AppendLine("refresh: FAILED " + Inner(ex)); return log.ToString(); }

        Assembly adomd = Assembly.LoadFrom(Path.Combine(bin, "Microsoft.PowerBI.AdomdClient.dll"));
        Type connT = adomd.GetType("Microsoft.AnalysisServices.AdomdClient.AdomdConnection");
        object conn = Activator.CreateInstance(connT, new object[] { "Data Source=localhost:" + port + ";Catalog=" + dbName });
        Call(conn, "Open");
        string[] queries = File.ReadAllText(queryFile, Encoding.UTF8).Split(new string[] { "\n-- next" }, StringSplitOptions.RemoveEmptyEntries);
        StringBuilder outp = new StringBuilder();
        int qn = 0;
        foreach (string q0 in queries) {
            string q = q0.Trim();
            if (q.Length == 0) continue;
            qn++;
            outp.AppendLine("## " + qn);
            try {
                object cmd = Call(conn, "CreateCommand");
                SetProp(cmd, "CommandText", q);
                object rdr = Call(cmd, "ExecuteReader");
                int fc = (int)Prop(rdr, "FieldCount");
                string[] names = new string[fc];
                for (int i = 0; i < fc; i++) names[i] = (string)Call(rdr, "GetName", i);
                outp.AppendLine(string.Join("\t", names));
                while ((bool)Call(rdr, "Read")) {
                    string[] vals = new string[fc];
                    for (int i = 0; i < fc; i++) {
                        object v = Call(rdr, "GetValue", i);
                        vals[i] = v == null || v is DBNull ? "" : Convert.ToString(v, System.Globalization.CultureInfo.InvariantCulture);
                    }
                    outp.AppendLine(string.Join("\t", vals));
                }
                Call(rdr, "Close");
            } catch (Exception ex) { outp.AppendLine("ERROR: " + Inner(ex)); }
        }
        Call(conn, "Close");
        File.WriteAllText(outFile, outp.ToString(), new UTF8Encoding(false));
        log.AppendLine("queries: " + qn);
        return log.ToString();
    }
}
"@
Add-Type -TypeDefinition $code -Language CSharp
Write-Output ([ModelRunner]::Run($Bin, $Port, (Resolve-Path $Folder).Path, $Database, (Resolve-Path $QueryFile).Path, $OutFile))
