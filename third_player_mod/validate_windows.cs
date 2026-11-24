using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class ThirdPlayerLoaderCheck {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr LoadLibraryEx(string path, IntPtr reserved, uint flags);
    [DllImport("kernel32.dll")]
    static extern bool FreeLibrary(IntPtr module);
    [DllImport("ntdll.dll")]
    static extern IntPtr RtlLookupFunctionEntry(ulong pc, out ulong imageBase, IntPtr history);

    public static string Check(string path, int helperRva) {
        // DONT_RESOLVE_DLL_REFERENCES maps the PE for inspection without running
        // DllMain, TLS initializers, or resolving/loading the Unity dependencies.
        IntPtr module = LoadLibraryEx(path, IntPtr.Zero, 1);
        if (module == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        try {
            ulong start = (ulong)module.ToInt64();
            foreach (int rva in new int[] {0x6ddf00, 0x1172ef0, helperRva}) {
                ulong image;
                IntPtr entry = RtlLookupFunctionEntry(start+(ulong)rva, out image, IntPtr.Zero);
                if (entry == IntPtr.Zero || image != start || Marshal.ReadInt32(entry) != rva)
                    throw new Exception("Windows could not resolve unwind entry at RVA "+rva.ToString("X"));
            }
            return "Windows mapped the patched DLL and resolved original/helper exception records. No game code was executed.";
        } finally { FreeLibrary(module); }
    }
}
