#define WIN32_LEAN_AND_MEAN
#include <windows.h>

static const WCHAR title[] = L"歌声工作台";
static WCHAR folder[32768];

static BOOL use_project_directory(void)
{
    DWORD n = GetModuleFileNameW(NULL, folder, 32768);
    if (n == 0 || n >= 32768) return FALSE;
    while (n && folder[n - 1] != L'\\') --n;
    if (!n) return FALSE;
    folder[n] = 0;
    return SetCurrentDirectoryW(folder);
}

/* CreateProcessW needs a writable command line. Both fragments below are
   fixed program strings; project paths are passed through the working directory. */
static BOOL run_python(const WCHAR *interpreter, const WCHAR *arguments, BOOL wait)
{
    WCHAR line[512];
    DWORD i = 0, result = 1;
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    while (*interpreter && i < 510) line[i++] = *interpreter++;
    if (*interpreter) return FALSE;
    line[i++] = L' ';
    while (*arguments && i < 511) line[i++] = *arguments++;
    if (*arguments) return FALSE;
    line[i] = 0;
    startup.cb = sizeof(startup);
    if (!CreateProcessW(NULL, line, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &startup, &process))
        return FALSE;
    CloseHandle(process.hThread);
    if (wait) {
        if (WaitForSingleObject(process.hProcess, INFINITE) == WAIT_OBJECT_0)
            GetExitCodeProcess(process.hProcess, &result);
    } else {
        result = 0;
    }
    CloseHandle(process.hProcess);
    return result == 0;
}

static BOOL start_with(const WCHAR *interpreter, const WCHAR *probe)
{
    return run_python(interpreter, probe, TRUE) &&
           run_python(interpreter, L"-I -X utf8 scripts\\bootstrap.pyw", FALSE);
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, LPWSTR command, int show)
{
    (void)instance; (void)previous; (void)command; (void)show;
    if (!use_project_directory() ||
        GetFileAttributesW(L"scripts\\bootstrap.pyw") == INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesW(L"voice_studio\\app.py") == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"请先完整解压项目，再双击其中的 VoiceCoverStudio.exe。", title, MB_OK | MB_ICONERROR);
        return 1;
    }
    SetEnvironmentVariableW(L"PYLAUNCHER_ALLOW_INSTALL", NULL);
    static const WCHAR existing[] = L"-I -c \"import sys; sys.exit(not (sys.maxsize > 2**32 and sys.version_info >= (3,11)))\"";
    static const WCHAR supported[] = L"-I -c \"import sys; sys.exit(not (sys.implementation.name == 'cpython' and sys.maxsize > 2**32 and sys.version_info[:2] in ((3,12),(3,11))))\"";
    if (GetFileAttributesW(L".studio\\Scripts\\python.exe") != INVALID_FILE_ATTRIBUTES &&
        start_with(L".studio\\Scripts\\python.exe", existing)) return 0;
    if (start_with(L"py.exe -3.12", supported)) return 0;
    if (start_with(L"py.exe -3.11", supported)) return 0;
    if (start_with(L"python.exe", supported)) return 0;
    MessageBoxW(NULL, L"未能启动 64 位 Python。请确认已安装 Python 3.12（含 3.12.10）或 3.11，并通过 py 启动器注册或添加到 PATH。", title, MB_OK | MB_ICONERROR);
    return 1;
}
