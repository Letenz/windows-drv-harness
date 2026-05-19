#include <ntddk.h>

DRIVER_UNLOAD HelloWorldUnload;

VOID
HelloWorldUnload(
    _In_ PDRIVER_OBJECT DriverObject
)
{
    UNREFERENCED_PARAMETER(DriverObject);
    DbgPrintEx(DPFLTR_IHVDRIVER_ID, DPFLTR_ERROR_LEVEL,
               "[HelloWorld] Driver unload, bye!\n");
}

NTSTATUS
DriverEntry(
    _In_ PDRIVER_OBJECT DriverObject,
    _In_ PUNICODE_STRING RegistryPath
)
{
    UNREFERENCED_PARAMETER(RegistryPath);

    DriverObject->DriverUnload = HelloWorldUnload;

    char* ptr = (char*)NULL;
    *ptr = 0x77;

    DbgPrintEx(DPFLTR_IHVDRIVER_ID, DPFLTR_ERROR_LEVEL,
               "[HelloWorld] Hello World from kernel! DriverObject=%p\n",
               DriverObject);

    return STATUS_SUCCESS;
}
