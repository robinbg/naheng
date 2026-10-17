"""Label actual native stops without treating policy limits as physical events."""

def stop_status(receipt, actual, requested_duration_s, trace_checks=None):
    origins = {item['constraint_origin'] for item in receipt['native_events_with_scope']}
    if 'native_physical_model' in origins:
        return 'native_physical_stop'
    if 'operational_stop' in origins:
        return 'operational_stop'
    if receipt['constraint_violations'] or (trace_checks and not all(trace_checks.values())):
        return 'realized_trace_constraint_stop'
    if actual.elapsed_s < requested_duration_s - 1e-8:
        return 'unknown_early_stop'
    return None
