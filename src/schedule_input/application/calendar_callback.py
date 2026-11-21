"""Apply one browser event before rendering the existing calendar again."""
from .calendar_edit import moved_task
from .mapper import TaskFactory


def handle_calendar_event(service, state, value):
    callback = value.get('callback')
    if callback == 'eventClick':
        task_id = value['eventClick']['event'].get('extendedProps', {}).get('task_id')
        if task_id in service.data._tasks:
            state['edit_request'] = (True, task_id)
        return
    if callback != 'eventChange':
        return
    change = value['eventChange']
    event = change['event']
    props = event.get('extendedProps', {})
    generation = state.get('calendar_sync', 0)
    # Ignore stale/replayed moves, including moves issued before the last save.
    if props.get('sync_revision') != generation:
        return
    state['calendar_sync'] = generation + 1
    state.pop('edit_request', None)
    state.pop('calendar_error', None)
    state.pop('calendar_message', None)
    try:
        task = service.data.get_by_id(props['task_id'])
        moved = moved_task(task, change['oldEvent']['start'], event['start'])
        report = service.submit(TaskFactory.to_row_view(moved), True)
        if report.has_errors():
            state['calendar_error'] = report
        else:
            state.pop('snapshot', None)
    except (ValueError, KeyError, OSError) as ex:
        state['calendar_message'] = str(ex)
    # A new sync_revision updates props even on rejection, restoring server data
    # without changing the component key or destroying its scroll position.
