#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <stdlib.h>
#include <wchar.h>

static void show_error(const wchar_t *reason, DWORD code)
{
    wchar_t message[640];
    swprintf(message, sizeof(message) / sizeof(message[0]),
             L"%ls (code %lu).\n\nCheck %%LOCALAPPDATA%%\\ReShadowTower\\launcher.log for details.",
             reason, (unsigned long)code);
    MessageBoxW(NULL, message, L"ReShadowTower", MB_OK | MB_ICONERROR);
}

static wchar_t *append(const wchar_t *dir, const wchar_t *suffix)
{
    size_t length = wcslen(dir) + wcslen(suffix) + 1;
    wchar_t *result = (wchar_t *)malloc(length * sizeof(wchar_t));
    if (result != NULL) {
        wcscpy(result, dir);
        wcscat(result, suffix);
    }
    return result;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR args, int show)
{
    wchar_t *dir = NULL, *python = NULL, *script = NULL, *command = NULL;
    DWORD capacity = MAX_PATH, length, exit_code = 1;
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    (void)instance;
    (void)previous;
    (void)args;
    (void)show;

    for (;;) {
        wchar_t *next = (wchar_t *)realloc(dir, (size_t)capacity * sizeof(wchar_t));
        if (next == NULL) {
            show_error(L"Unable to allocate launcher path", ERROR_OUTOFMEMORY);
            goto done;
        }
        dir = next;
        SetLastError(ERROR_SUCCESS);
        length = GetModuleFileNameW(NULL, dir, capacity);
        if (length == 0) {
            show_error(L"Unable to locate ReShadowTower.exe", GetLastError());
            goto done;
        }
        if (length < capacity) break;
        if (capacity > 32768) {
            show_error(L"Installation path is too long", ERROR_BUFFER_OVERFLOW);
            goto done;
        }
        capacity *= 2;
    }
    {
        wchar_t *separator = wcsrchr(dir, L'\\');
        if (separator == NULL) {
            show_error(L"Unable to locate installation directory", ERROR_BAD_PATHNAME);
            goto done;
        }
        *separator = L'\0';
    }
    python = append(dir, L"\\toolchain\\python\\python.exe");
    script = append(dir, L"\\launch_release.py");
    if (python == NULL || script == NULL) {
        show_error(L"Unable to allocate launcher command", ERROR_OUTOFMEMORY);
        goto done;
    }
    /* Windows paths cannot contain quotes; quote both arguments for spaces. */
    command = (wchar_t *)malloc((wcslen(python) + wcslen(script) + 16) * sizeof(wchar_t));
    if (command == NULL) {
        show_error(L"Unable to allocate launcher command", ERROR_OUTOFMEMORY);
        goto done;
    }
    swprintf(command, wcslen(python) + wcslen(script) + 16,
             L"\"%ls\" -I -B \"%ls\"", python, script);
    startup.cb = sizeof(startup);
    if (!CreateProcessW(python, command, NULL, NULL, FALSE, CREATE_NO_WINDOW,
                        NULL, dir, &startup, &process)) {
        show_error(L"Unable to start bundled Python; check the installation", GetLastError());
        goto done;
    }
    if (WaitForSingleObject(process.hProcess, INFINITE) != WAIT_OBJECT_0) {
        show_error(L"Unable to wait for ReShadowTower", GetLastError());
        goto done;
    }
    if (!GetExitCodeProcess(process.hProcess, &exit_code)) {
        show_error(L"Unable to read ReShadowTower exit status", GetLastError());
        exit_code = 1;
    } else if (exit_code != 0) {
        show_error(L"ReShadowTower exited with an error", exit_code);
    }
done:
    if (process.hThread != NULL) CloseHandle(process.hThread);
    if (process.hProcess != NULL) CloseHandle(process.hProcess);
    free(command);
    free(script);
    free(python);
    free(dir);
    return (int)exit_code;
}
