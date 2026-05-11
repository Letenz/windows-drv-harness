# Workflow: Build/Test/Fix Loop

Use this when the user wants the AI to modify driver code based on VM test
results.

## Loop

1. Build the driver with the repo's existing build command. Do not change build
   systems unless the failure requires it.
2. Run `driver-harness-mcp.diagnose_environment`. Fix environment blockers
   before interpreting test failures as code bugs.
3. Run `driver-harness-mcp.run_driver_load_verify` with the built `.sys`.
4. If `verdict=PASS`, summarize the evidence and stop.
5. If `verdict=FAIL`, classify the failure:
   - Environment/setup failure: repair config, monitor, VM tools, snapshot, or
     debugger connection.
   - Driver load/service failure: inspect DriverEntry, INF/service name, signing,
     architecture, and import compatibility.
   - Runtime crash: read `.bugcheck`, `!analyze -v`, stack, and driver symbols.
   - Missing marker/module evidence: inspect logging path, unload routine, and
     module name assumptions.
6. Patch the smallest relevant code area.
7. Rebuild and rerun the same high-level test once.

## Discipline

- Keep each iteration tied to one observed failure.
- Preserve artifacts from the tool result in the summary.
- Stop after repeated identical environment failures and ask for the missing
  host/guest fact.
- Do not create new automation scripts unless no MCP tool can perform the step.
