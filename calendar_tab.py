#!/usr/bin/env python3
"""
Calendar Tab Component for Referee Mentor System
Handles calendar display and event management using FullCalendar.js
"""

import json
import logging
import uuid
from datetime import date, datetime
from nicegui import ui


class CalendarTab:
    """Calendar tab component with event management functionality"""

    def __init__(self, db, auth_manager, logger=None):
        """
        Initialize the calendar tab component

        Args:
            db: Database connection object (RefereeDbCockroach instance)
            auth_manager: Authentication manager instance
            logger: Optional logger instance (defaults to module logger)
        """
        self.db = db
        self.auth_manager = auth_manager
        self.logger = logger or logging.getLogger(__name__)
        self.current_user = None
        self.calendar_container = None
        self.date_trigger = None
        self.event_trigger = None
        self.event_move_trigger = None

    def _load_events(self):
        """Load events from database and format for FullCalendar"""
        try:
            db_events = self.db.getCalendarEvents()
            fc_events = []
            for event in db_events:
                # Format for FullCalendar
                start_str = str(event['start_date'])
                if event['start_time']:
                    start_str += f"T{event['start_time']}:00"

                fc_event = {
                    'id': str(event['id']),
                    'title': event['title'],
                    'start': start_str,
                    'allDay': not event['start_time'],
                    'extendedProps': {
                        'description': event['description'],
                        'created_by': event['created_by'],
                        'event_id': event['id']
                    }
                }

                if event.get('end_date'):
                    end_str = str(event['end_date'])
                    if event.get('end_time'):
                        end_str += f"T{event['end_time']}:00"
                    fc_event['end'] = end_str

                fc_events.append(fc_event)
            return fc_events
        except Exception as e:
            self.logger.error(f"Error loading events: {e}", exc_info=True)
            return []

    def _refresh_calendar(self):
        """Refresh the calendar with updated events"""
        events = self._load_events()
        events_json = json.dumps(events)
        ui.run_javascript(f'''
            if (window.calendarInstance) {{
                window.calendarInstance.removeAllEvents();
                window.calendarInstance.addEventSource({events_json});
            }}
        ''')

    def _open_add_event_dialog(self, prefill_date=None):
        """Open dialog to add a new event"""
        today = date.today()

        with ui.dialog() as dialog, ui.card().classes('p-6').style('min-width: 400px'):
            ui.label('Add New Event').classes('text-xl font-bold mb-4')

            title_input = ui.input(label='Title', placeholder='Event title').classes('w-full')
            description_input = ui.textarea(label='Description', placeholder='Event description').classes('w-full')
            description_input.props('rows=3')

            with ui.column().classes('w-full gap-2'):
                ui.label('Start Date & Time').classes('text-sm font-medium')
                with ui.row().classes('w-full gap-4 items-center'):
                    start_date_input = ui.date(value=prefill_date or today.isoformat()).classes('flex-1')
                    start_time_input = ui.time(value=None).classes('flex-1')

            with ui.column().classes('w-full gap-2 mt-4'):
                ui.label('End Date & Time (optional)').classes('text-sm font-medium')
                with ui.row().classes('w-full gap-4 items-center'):
                    end_date_input = ui.date(value=None).classes('flex-1')
                    end_time_input = ui.time(value=None).classes('flex-1')

            def save_event():
                title = title_input.value
                if not title:
                    ui.notify('Please enter a title', type='warning')
                    return

                start_date = start_date_input.value
                end_date = end_date_input.value if end_date_input.value else None
                start_time = start_time_input.value if start_time_input.value else None
                end_time = end_time_input.value if end_time_input.value else None
                description = description_input.value or ''

                success, message, event_id = self.db.addCalendarEvent(
                    title=title,
                    description=description,
                    start_date=start_date,
                    end_date=end_date,
                    start_time=start_time,
                    end_time=end_time,
                    created_by=self.current_user or 'unknown'
                )

                if success:
                    ui.notify(message, type='positive')
                    dialog.close()
                    self._refresh_calendar()
                else:
                    ui.notify(message, type='negative')

            with ui.row().classes('w-full justify-end gap-2 mt-4'):
                ui.button('Cancel', on_click=dialog.close).props('flat')
                ui.button('Save', on_click=save_event).props('color=primary')

        dialog.open()

    def _open_edit_event_dialog(self, event_id):
        """Open dialog to edit an existing event"""
        event = self.db.getCalendarEvent(event_id)
        if not event:
            ui.notify('Event not found', type='negative')
            return

        with ui.dialog() as dialog, ui.card().classes('p-6').style('min-width: 400px'):
            ui.label('Edit Event').classes('text-xl font-bold mb-4')

            title_input = ui.input(label='Title', value=event['title']).classes('w-full')
            description_input = ui.textarea(label='Description', value=event['description']).classes('w-full')
            description_input.props('rows=3')

            start_date_val = event['start_date']
            if isinstance(start_date_val, date):
                start_date_val = start_date_val.isoformat()
            elif isinstance(start_date_val, datetime):
                start_date_val = start_date_val.date().isoformat()

            with ui.column().classes('w-full gap-2'):
                ui.label('Start Date & Time').classes('text-sm font-medium')
                with ui.row().classes('w-full gap-4 items-center'):
                    start_date_input = ui.date(value=start_date_val).classes('flex-1')
                    start_time_input = ui.time(value=event['start_time']).classes('flex-1')

            with ui.column().classes('w-full gap-2 mt-4'):
                ui.label('End Date & Time (optional)').classes('text-sm font-medium')
                with ui.row().classes('w-full gap-4 items-center'):
                    end_date_val = event.get('end_date')
                    if end_date_val:
                        if isinstance(end_date_val, date):
                            end_date_val = end_date_val.isoformat()
                        elif isinstance(end_date_val, datetime):
                            end_date_val = end_date_val.date().isoformat()
                    end_date_input = ui.date(value=end_date_val).classes('flex-1')
                    end_time_input = ui.time(value=event.get('end_time')).classes('flex-1')

            def save_changes():
                title = title_input.value
                if not title:
                    ui.notify('Please enter a title', type='warning')
                    return

                start_date = start_date_input.value
                end_date = end_date_input.value if end_date_input.value else None
                start_time = start_time_input.value if start_time_input.value else None
                end_time = end_time_input.value if end_time_input.value else None
                description = description_input.value or ''

                success, message = self.db.updateCalendarEvent(
                    event_id=event_id,
                    title=title,
                    description=description,
                    start_date=start_date,
                    end_date=end_date,
                    start_time=start_time,
                    end_time=end_time
                )

                if success:
                    ui.notify(message, type='positive')
                    dialog.close()
                    self._refresh_calendar()
                else:
                    ui.notify(message, type='negative')

            def delete_event():
                success, message = self.db.deleteCalendarEvent(event_id)
                if success:
                    ui.notify(message, type='positive')
                    dialog.close()
                    self._refresh_calendar()
                else:
                    ui.notify(message, type='negative')

            with ui.row().classes('w-full justify-between mt-4'):
                ui.button('Delete', on_click=delete_event, icon='delete').props('flat color=red')
                with ui.row().classes('gap-2'):
                    ui.button('Cancel', on_click=dialog.close).props('flat')
                    ui.button('Save', on_click=save_changes).props('color=primary')

        dialog.open()

    def _check_triggers(self):
        """Check for date/event selections from JavaScript"""
        if self.date_trigger.value:
            date_val = self.date_trigger.value
            self.date_trigger.value = ''  # Reset
            self._open_add_event_dialog(date_val)

        if self.event_trigger.value:
            event_id_val = int(self.event_trigger.value)
            self.event_trigger.value = ''  # Reset
            self._open_edit_event_dialog(event_id_val)

        if self.event_move_trigger.value:
            # Format: "eventId:newDate"
            parts = self.event_move_trigger.value.split(':')
            if len(parts) == 2:
                event_id_val = int(parts[0])
                new_date = parts[1]
                self.event_move_trigger.value = ''  # Reset
                # Update event date
                event = self.db.getCalendarEvent(event_id_val)
                if event:
                    success, message = self.db.updateCalendarEvent(
                        event_id=event_id_val,
                        title=event['title'],
                        description=event['description'],
                        start_date=new_date,
                        end_date=event.get('end_date'),
                        start_time=event.get('start_time'),
                        end_time=event.get('end_time')
                    )
                    if success:
                        ui.notify('Event moved', type='positive')
                        self._refresh_calendar()
                    else:
                        ui.notify(message, type='negative')
                        self._refresh_calendar()  # Refresh to revert on error

    def _initialize_calendar(self):
        """Initialize calendar with proper trigger setup"""
        events = self._load_events()
        events_json = json.dumps(events)
        date_trigger_id = self.date_trigger.id
        event_trigger_id = self.event_trigger.id
        event_move_trigger_id = self.event_move_trigger.id
        # Use the container ID we set when creating the element
        container_id = getattr(self, '_calendar_container_id', f'calendar-container-{self.calendar_container.id}')

        # Use run_javascript to initialize the calendar
        # This ensures FullCalendar is loaded and DOM is ready
        init_script = f'''
        (function() {{
            function initCalendar() {{
                // Check if FullCalendar is loaded (it's available as FullCalendar global)
                if (typeof FullCalendar === 'undefined') {{
                    console.log('[Calendar] FullCalendar not loaded yet, retrying in 200ms...');
                    setTimeout(initCalendar, 200);
                    return;
                }}

                const containerId = '{container_id}';
                let calendarEl = document.getElementById(containerId);
                if (!calendarEl) {{
                    console.log('[Calendar] Container element not found (ID: ' + containerId + '), retrying in 200ms...');
                    setTimeout(initCalendar, 200);
                    return;
                }}

                console.log('[Calendar] Container found, initializing FullCalendar...');

                // Remove existing calendar if any
                if (window.calendarInstance) {{
                    try {{
                        console.log('[Calendar] Destroying existing calendar instance');
                        window.calendarInstance.destroy();
                    }} catch (e) {{
                        console.warn('[Calendar] Error destroying existing calendar:', e);
                    }}
                }}

                const events = {events_json};
                console.log('[Calendar] Initializing with', events.length, 'events');

                try {{
                    var calendar = new FullCalendar.Calendar(calendarEl, {{
                        initialView: 'dayGridMonth',
                        headerToolbar: {{
                            left: 'prev,next today',
                            center: 'title',
                            right: 'dayGridMonth,timeGridWeek,timeGridDay,listWeek'
                        }},
                        editable: true,
                        selectable: true,
                        selectMirror: true,
                        dayMaxEvents: true,
                        events: events,
                        select: function(arg) {{
                            const selectedDate = arg.startStr.split('T')[0];
                            const dateInput = document.getElementById('{date_trigger_id}');
                            if (dateInput) {{
                                dateInput.value = selectedDate;
                                dateInput.dispatchEvent(new Event('input'));
                            }}
                            calendar.unselect();
                        }},
                        eventClick: function(arg) {{
                            const eventId = arg.event.extendedProps.event_id;
                            const eventInput = document.getElementById('{event_trigger_id}');
                            if (eventInput) {{
                                eventInput.value = eventId;
                                eventInput.dispatchEvent(new Event('input'));
                            }}
                        }},
                        eventDrop: function(arg) {{
                            const eventId = parseInt(arg.event.extendedProps.event_id);
                            const newStart = arg.event.startStr.split('T')[0];
                            const moveInput = document.getElementById('{event_move_trigger_id}');
                            if (moveInput) {{
                                moveInput.value = eventId + ':' + newStart;
                                moveInput.dispatchEvent(new Event('input'));
                            }}
                        }}
                    }});
                    calendar.render();
                    window.calendarInstance = calendar;
                    console.log('[Calendar] FullCalendar initialized successfully');
                }} catch (error) {{
                    console.error('[Calendar] Error initializing FullCalendar:', error);
                    console.error('[Calendar] Error stack:', error.stack);
                }}
            }}

            // Start initialization after a brief delay to ensure everything is ready
            setTimeout(initCalendar, 100);
        }})();
        '''

        ui.run_javascript(init_script)

    def render(self):
        """Render the calendar tab with FullCalendar.js integration"""
        # Get current user
        self.current_user = self.auth_manager.get_current_user()

        with ui.card().classes('form-container w-full'):
            with ui.row().classes('w-full justify-between items-center mb-4'):
                ui.label('Calendar').classes('text-xl font-bold')
                ui.button('Add Event', icon='add', on_click=lambda: self._open_add_event_dialog(None)).props('color=primary')

            # Add FullCalendar.js CSS and JS via HTML (must be done before creating calendar container)
            ui.add_head_html('''
                <link href='https://cdn.jsdelivr.net/npm/fullcalendar@6.1.10/index.global.min.css' rel='stylesheet' />
                <script src='https://cdn.jsdelivr.net/npm/fullcalendar@6.1.10/index.global.min.js'></script>
            ''')

            # Calendar container - create a div element with explicit ID
            self._calendar_container_id = f'calendar-container-{uuid.uuid4().hex[:8]}'
            # Create the container and set its ID using props
            self.calendar_container = ui.element('div').classes('w-full').style('height: 600px; min-height: 600px;').props(f'id={self._calendar_container_id}')

            # Create hidden storage elements for JavaScript-Python communication
            self.date_trigger = ui.input('').style('display: none')
            self.event_trigger = ui.input('').style('display: none')
            self.event_move_trigger = ui.input('').style('display: none')  # Format: "eventId:newDate"

            # Poll for changes (simple but effective)
            ui.timer(0.5, self._check_triggers)

            # Initialize calendar after a delay to ensure DOM and FullCalendar are ready
            # Use a longer delay to ensure FullCalendar.js has loaded
            def delayed_init():
                self._initialize_calendar()

            ui.timer(1.0, delayed_init, once=True)

            # Add a refresh button
            def manual_refresh():
                self._initialize_calendar()
                ui.notify('Calendar refreshed', type='info')

            ui.button('Refresh Calendar', icon='refresh', on_click=manual_refresh).classes('mt-2')
