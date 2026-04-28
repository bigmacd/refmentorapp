#!/usr/bin/env python3
"""
NiceGUI-based Referee Mentor System
Converted from Streamlit version
"""

import logging
from datetime import datetime as dtime
import os
from typing import Tuple

# Create logger for this module
import rmaLogging

from fastapi import Response
from fastapi.staticfiles import StaticFiles
from nicegui import ui, app

from appState import AppState
from calendar_tab import CalendarTab
from excelWriter import getExcelFromText
from mentor_game_selection import MentorGameSelection

logger = logging.getLogger(__name__)

state = AppState(logger, ui)

# Serve static files (PWA manifest, icons)
_static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
if os.path.isdir(_static_dir):
    app.add_static_files('/static', _static_dir)

# Handle Streamlit-specific endpoints that bots/bookmarks might request
# These return 200 to prevent 404 errors in logs without interfering with Socket.IO
@app.get('/_stcore/host-config')
def handle_streamlit_host_config():
    """Handle Streamlit host-config endpoint requests"""
    return Response(status_code=200, content="", media_type="application/json")


@app.get('/_stcore/health')
def handle_streamlit_health():
    """Handle Streamlit health endpoint requests"""
    return Response(status_code=200, content="", media_type="application/json")


@app.get('/_nicegui_ws/health')
def handle_websocket_health():
    """Diagnostic endpoint to check WebSocket server status"""
    import sys
    is_debug = hasattr(sys, 'gettrace') and sys.gettrace() is not None
    return {
        'status': 'ok',
        'websocket_path': '/_nicegui_ws/socket.io/',
        'debug_mode': is_debug,
        'message': 'WebSocket server is running' + (' (debug mode may affect connections)' if is_debug else '')
    }



def parse_ref_name(name: str) -> Tuple[str, str]:
    """Parse referee name handling various formats"""
    if name == '(requested)':
        return (None, None)

    name = ' '.join(name.split())
    parts = name.split(',')
    if len(parts) > 1:
        first_parts = parts[1].strip().split()
        return (first_parts[0], parts[0].strip())

    parts = name.split(' ')
    if len(parts) == 0:
        return (None, None)
    elif len(parts) == 1:
        return (parts[0], "")
    elif len(parts) == 2:
        return (parts[0], parts[1])
    else:
        suffixes = ["Jr.", "Jr", "Sr.", "Sr", "III", "IV", "II"]
        if parts[-1] in suffixes:
            return (parts[0], ' '.join(parts[1:-1]) + ' ' + parts[-1])
        else:
            return (parts[0], ' '.join(parts[1:]))


def get_current_date_index(dates: list) -> int:
    fs = "%A, %B %d, %Y"
    today = dtime.now()
    fd = today.strftime(fs)
    today = dtime.strptime(fd, fs)
    for index, d in enumerate(dates):
        this_date = dtime.strptime(d, fs)
        if this_date >= today:
            return index
    return 0


@ui.page('/')
def main_page():
    ui.dark_mode(True)
    # Check authentication FIRST - before ANY UI is created
    is_auth = state.auth_manager.is_authenticated()

    if not is_auth:
        # Use meta refresh for immediate redirect (happens before page renders)
        ui.add_head_html('''
            <meta http-equiv="refresh" content="0; url=/login">
            <script>
                // Backup: immediate JavaScript redirect
                if (window.location.pathname !== '/login') {
                    window.location.replace('/login');
                }
            </script>
        ''')
        # Return immediately - don't create any UI
        return

    # Only proceed if authenticated - show loading state first
    # Create a loading overlay that will be shown while data loads
    loading_overlay = ui.column().classes('fixed inset-0 bg-white bg-opacity-90 dark:bg-gray-900 dark:bg-opacity-90 items-center justify-center z-50')
    with loading_overlay:
        ui.spinner(size='xl')
        ui.label('Loading data...').classes('mt-4 text-xl text-gray-700 dark:text-gray-300')

    # Poll for data if background load is still in progress
    def wait_for_background_load():
        # Always check if data is loaded first (background thread might have completed)
        if state.is_data_loaded():
            # Data is loaded, hide overlay using CSS (most reliable method)
            logger.info("Data loaded, hiding loading overlay")
            loading_overlay.style('display: none !important')
            return

        # If still loading, continue polling
        if state.is_loading():
            logger.debug("Data still loading, will check again in 0.3 seconds")
            ui.timer(0.3, wait_for_background_load, once=True)
            return

        # Not loading and not loaded - try to trigger load
        # This handles the case where background load hasn't started yet or failed silently
        logger.info("Data not loaded and not loading, attempting to load...")
        try:
            state.load_data()
            # After calling load_data, check again after a short delay
            # to see if it completed (unlikely but possible for fast loads)
            ui.timer(0.1, wait_for_background_load, once=True)
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            loading_overlay.clear()
            with loading_overlay:
                ui.label('Error loading data').classes('text-red-500 text-xl')
                ui.label(str(e)).classes('text-gray-600 dark:text-gray-400 mt-2')
                ui.button('Retry', on_click=lambda: ui.navigate.reload()).classes('mt-4')

    # Check immediately if data is already loaded (from background thread)
    # This handles the case where background load completed before page render
    if state.is_data_loaded():
        logger.info("Data already loaded when page rendered, hiding loading overlay")
        loading_overlay.style('display: none !important')
    else:
        # Start polling for background load completion
        ui.timer(0.1, wait_for_background_load, once=True)


    # PWA manifest
    ui.add_head_html('<link rel="manifest" href="/static/manifest.json">')

    # Custom CSS
    ui.add_head_html('''
    <style>
        .tab-button {
            padding: 12px 24px;
            margin: 4px;
            border-radius: 8px;
            font-weight: 500;
        }
        .tab-button.active {
            background-color: #1976d2 !important;
            color: white !important;
        }
        .form-container {
            width: 100% !important;
            max-width: none !important;
            padding: 20px;
        }
        .checkbox-row {
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }
    </style>
    ''')

    with ui.header().classes('bg-blue-900 text-white'):
        ui.label('🏆 Referee Mentor System').classes('text-2xl font-bold')

    # Left sidebar for user menu
    with ui.left_drawer(top_corner=True, bottom_corner=True).classes('p-4'):
        current_user = state.auth_manager.get_current_user()
        if current_user:  # Only show if user is actually logged in
            ui.label(f'Logged in as:').classes('text-gray-600 text-sm')
            ui.label(f'{current_user}').classes('font-bold mb-2')
            user_role = state.auth_manager.get_user_role()
            if user_role:
                ui.label(f'Role: {user_role}').classes('text-gray-600 text-sm mb-4')

        ui.separator()

        ui.button('Change Password', on_click=lambda: ui.navigate.to('/change-password')).classes('w-full mt-4').props('flat')
        ui.button('Logout', on_click=lambda: state.auth_manager.logout()).classes('w-full mt-2').props('flat color=red')

        if state.auth_manager.is_admin():
            ui.separator().classes('my-4')
            ui.label('Admin Functions').classes('font-bold text-sm')
            ui.button('User Management', on_click=lambda: ui.navigate.to('/admin/users')).classes('w-full mt-2').props('flat')

        ui.label('Version: ' + open('VERSION', 'r').read().strip()).classes('text-gray-600 text-right w-full mb-6')



    # Tab navigation using NiceGUI tabs
    with ui.tabs().classes('w-full') as tabs:
        tab_report = ui.tab('📥 Report', 'Enter a Mentor Report')
        tab_generate = ui.tab('📤 Generate', 'Generate Reports')
        tab_workload = ui.tab('📝 Workload', 'See Current Workload')
        tab_select_games = ui.tab('🎯 Select Games', 'Select Games to Mentor')
        tab_calendar = ui.tab('🗓 Calendar', 'Calendar')

    # Content container
    content = ui.tab_panels(tabs, value=tab_report).classes('w-full')

    # Initialize tab components
    calendar_tab = CalendarTab(state.db, state.auth_manager, logger)
    game_selection_tab = MentorGameSelection(
        state.db, state.auth_manager, state.all_match_data, state.dates, logger,
        get_match_data=lambda: (state.all_match_data, state.dates)
    )

    with content:
        with ui.tab_panel(tab_report):
            render_mentor_report_tab()
        with ui.tab_panel(tab_generate):
            render_reports_tab()
        with ui.tab_panel(tab_workload):
            render_workload_tab()
        with ui.tab_panel(tab_select_games):
            game_selection_tab.render()
        with ui.tab_panel(tab_calendar):
            calendar_tab.render()


def render_mentor_report_tab():
    """Render the mentor report entry form"""
    card = ui.card().classes('form-container w-full')
    if not state.is_data_loaded():
        with card:
            with ui.column().classes('items-center justify-center p-8'):
                ui.spinner(size='lg')
                ui.label('Loading data...').classes('mt-4 text-gray-600')
                ui.label('Checking every few seconds. Data will appear when ready.').classes('text-sm text-gray-500 mt-2')
        def check_loaded():
            if state.is_data_loaded():
                card.clear()
                _build_mentor_report_form(card)
            else:
                if not state.is_loading():
                    state._start_background_load()
                ui.timer(0.5, check_loaded, once=True)
        ui.timer(0.5, check_loaded, once=True)
        return
    _build_mentor_report_form(card)


def _build_mentor_report_form(container):
    """Build the mentor report form inside the given container."""
    # Form state
    form_state = {
        'mentor': None,
        'date': None,
        'venue': None,
        'game': None,
        'center_cb': False,
        'ar1_cb': False,
        'ar2_cb': False,
        'revisit_center': False,
        'revisit_ar1': False,
        'revisit_ar2': False,
        'comments': '',
        'current_match': None
    }

    with container:
        ui.label('Enter a Mentor Report').classes('text-xl font-bold mb-4')

        # Mentor selection
        mentors = state.db.getMentors()
        mentor_values = sorted([f'{m[0].capitalize()} {m[1].capitalize()}' for m in mentors])

        # Filter to current user if not admin
        current_user = state.auth_manager.get_current_user()
        if current_user and not current_user.startswith('martin'):
            filtered = [v for v in mentor_values if v.lower().startswith(current_user.lower())]
            if filtered:
                mentor_values = filtered

        mentor_select = ui.select(mentor_values, label='Select Mentor', value=mentor_values[0] if mentor_values else None)
        mentor_select.classes('w-full')

        # Date selection
        date_index = get_current_date_index(state.dates)
        if date_index < len(state.dates) and state.dates[date_index].startswith('Tuesday'):
            date_index = min(date_index + 1, len(state.dates) - 1)

        date_select = ui.select(state.dates, label='Select Date', value=state.dates[date_index] if state.dates else None)
        date_select.classes('w-full')

        # Venue selection (dynamic based on date)
        venue_select = ui.select([], label='Select Venue')
        venue_select.classes('w-full')

        # Game selection (dynamic based on venue)
        game_select = ui.select([], label='Select Game')
        game_select.classes('w-full')

        # Referee checkboxes container
        ui.label('Select referees being mentored:').classes('mt-4 font-semibold')
        with ui.row().classes('checkbox-row'):
            center_cb = ui.checkbox('Center: --')
            ar1_cb = ui.checkbox('AR1: --')
            ar2_cb = ui.checkbox('AR2: --')

        # Comments
        comments = ui.textarea(label='Comments', placeholder='Enter your mentoring comments here...').classes('w-full mt-4')
        comments.props('rows=10')

        # Revisit checkboxes
        ui.label('Should any referee be revisited?').classes('mt-4 font-semibold')
        with ui.row().classes('checkbox-row'):
            revisit_center = ui.checkbox('Revisit Center')
            revisit_ar1 = ui.checkbox('Revisit AR1')
            revisit_ar2 = ui.checkbox('Revisit AR2')

        # Message area
        message_area = ui.column().classes('w-full mt-4')

        def update_venues():
            selected_date = date_select.value
            if selected_date and selected_date in state.all_match_data:
                matches = state.all_match_data[selected_date]
                venues = sorted(list(matches.keys()))
                venue_select.options = venues
                venue_select.value = venues[0] if venues else None
                update_games()

        def update_games():
            selected_date = date_select.value
            selected_venue = venue_select.value
            if selected_date and selected_venue and selected_date in state.all_match_data:
                matches = state.all_match_data[selected_date]
                if selected_venue in matches:
                    games = matches[selected_venue]
                    game_options = [f"Time-{g['Time']}" for g in games]
                    game_select.options = game_options
                    game_select.value = game_options[0] if game_options else None
                    update_refs()

        def update_refs():
            selected_date = date_select.value
            selected_venue = venue_select.value
            selected_game = game_select.value

            if not all([selected_date, selected_venue, selected_game]):
                return

            matches = state.all_match_data.get(selected_date, {})
            games = matches.get(selected_venue, [])

            game_time = selected_game.split('-')[1] if selected_game else None
            current_match = None
            for g in games:
                if g['Time'] == game_time:
                    current_match = g
                    break

            form_state['current_match'] = current_match

            if current_match:
                center_cb.text = f"Center: {current_match.get('Center', '--')}"
                ar1_cb.text = f"AR1: {current_match.get('AR1', '--')}"
                ar2_cb.text = f"AR2: {current_match.get('AR2', '--')}"

        date_select.on_value_change(lambda: update_venues())
        venue_select.on_value_change(lambda: update_games())
        game_select.on_value_change(lambda: update_refs())

        # Initial load
        update_venues()

        def do_save():
            current_match = form_state['current_match']
            if not current_match:
                with message_area:
                    ui.notify('Please select a game first', type='warning')
                return

            mentor = mentor_select.value
            if not mentor:
                ui.notify('Please select a mentor', type='warning')
                return

            refs = [center_cb.value, ar1_cb.value, ar2_cb.value]
            positions = ['Center', 'AR1', 'AR2']

            if not any(refs):
                ui.notify('Please select at least one referee', type='warning')
                return

            for i, ref_selected in enumerate(refs):
                if ref_selected:
                    ref_name = current_match[positions[i]]
                    revisit = (positions[i] == "Center" and revisit_center.value) or \
                              (positions[i] == "AR1" and revisit_ar1.value) or \
                              (positions[i] == "AR2" and revisit_ar2.value)

                    status, message = state.db.addMentorSessionNew(
                        mentor.lower(),
                        ref_name.lower(),
                        positions[i],
                        date_select.value,
                        comments.value,
                        revisit,
                        current_match.get('GameID', '')
                    )

                    if status:
                        ui.notify(f'{message}: Referee {ref_name}', type='positive')
                    else:
                        ui.notify(f'Error: {message}', type='negative')

            # Reset form
            center_cb.value = False
            ar1_cb.value = False
            ar2_cb.value = False
            revisit_center.value = False
            revisit_ar1.value = False
            revisit_ar2.value = False
            comments.value = ''

        def do_cancel():
            center_cb.value = False
            ar1_cb.value = False
            ar2_cb.value = False
            revisit_center.value = False
            revisit_ar1.value = False
            revisit_ar2.value = False
            comments.value = ''

        # Buttons
        with ui.row().classes('w-full justify-between mt-4'):
            ui.button('Save', on_click=do_save).props('color=primary')
            ui.button('Cancel', on_click=do_cancel).props('color=grey')


def render_reports_tab():
    """Render the reports generation tab"""

    with ui.card().classes('form-container w-full'):
        ui.label('Generate Reports').classes('text-xl font-bold mb-4')

        # Report format
        format_select = ui.radio(['Text', 'Excel'], value='Text').props('inline')

        # Report type
        year_data = state.db.getYears()
        year_data.insert(0, ' ')

        report_type = ui.select(
            ['by year', 'by week', 'by referee', 'by mentor'],
            label='Report Type',
            value='by year'
        ).classes('w-full')

        # Dynamic selection container
        selection_container = ui.column().classes('w-full')

        # Download area
        download_area = ui.column().classes('w-full mt-4')

        current_selection = {'type': None, 'value': None}

        def update_selection():
            selection_container.clear()
            download_area.clear()

            with selection_container:
                if report_type.value == 'by year':
                    sel = ui.select(year_data, label='Select Year').classes('w-full')
                    sel.on_value_change(lambda: set_selection('year', sel.value))

                elif report_type.value == 'by week':
                    weeks = [' '] + state.dates
                    sel = ui.select(weeks, label='Select Week').classes('w-full')
                    sel.on_value_change(lambda: set_selection('week', sel.value))

                elif report_type.value == 'by referee':
                    referees = [' '] + state.db.getRefereesForSelectionBox()
                    sel = ui.select(referees, label='Select Referee').classes('w-full')
                    sel.on_value_change(lambda: set_selection('referee', sel.value))

                elif report_type.value == 'by mentor':
                    mentors = [' '] + state.db.getMentorsForSelectionBox()
                    sel = ui.select(mentors, label='Select Mentor').classes('w-full')
                    sel.on_value_change(lambda: set_selection('mentor', sel.value))

        def set_selection(sel_type, value):
            current_selection['type'] = sel_type
            current_selection['value'] = value
            update_download_button()

        def update_download_button():
            download_area.clear()

            if not current_selection['value'] or current_selection['value'] == ' ':
                return

            with download_area:
                ui.button('Generate Report', on_click=generate_report).props('color=primary')

        def generate_report():
            sel_type = current_selection['type']
            sel_value = current_selection['value']
            report_format = format_select.value

            if not sel_value or sel_value == ' ':
                ui.notify('Please make a selection', type='warning')
                return

            try:
                if sel_type == 'year':
                    data = state.db.produceYearReport(sel_value)
                elif sel_type == 'week':
                    data = state.db.produceWeekReport(sel_value)
                elif sel_type == 'referee':
                    data = state.db.produceRefereeReport(sel_value)
                elif sel_type == 'mentor':
                    data = state.db.produceMentorReport(sel_value)
                else:
                    return

                if report_format == 'Text':
                    ui.download(data.encode(), f'report.txt')
                else:
                    getExcelFromText(data)
                    with open('report.xlsx', 'rb') as f:
                        ui.download(f.read(), 'report.xlsx')

            except Exception as e:
                ui.notify(f'Error generating report: {str(e)}', type='negative')

        report_type.on_value_change(lambda: update_selection())
        update_selection()


def render_workload_tab():
    """Render the current workload tab"""

    with ui.card().classes('form-container w-full'):
        ui.label('Current Workload').classes('text-xl font-bold mb-4')

        # Use ui.label + .text (BindableProperty) so updates reach the browser.
        # ui.code's .content is not bound the same way; assigning it often does not refresh the client.
        output_area = ui.label('Loading workload data...').classes(
            'w-full whitespace-pre-wrap font-mono text-sm p-4 rounded bg-gray-900'
        )

        def check_workload_status():
            """Check if workload loading is complete and update UI"""
            if not state.workload_loading:
                # Loading is complete, update UI
                if state.workload_error:
                    output_area.text = f'Error loading workload: {state.workload_error}'
                elif state.workload_output:
                    output_area.text = state.workload_output
                elif ui.resultsFromRun:
                    # Data is available but output wasn't captured, show success message
                    output_area.text = 'Workload data loaded successfully.'
                else:
                    output_area.text = 'No workload data available'
                # Timer will stop automatically since we don't reschedule
            else:
                # Still loading, check again in 0.5 seconds
                ui.timer(0.5, check_workload_status, once=True)

        # Check if already loaded
        if not state.workload_loading:
            if state.workload_error:
                output_area.text = f'Error loading workload: {state.workload_error}'
            elif state.workload_output:
                output_area.text = state.workload_output
            elif hasattr(ui, 'resultsFromRun') and ui.resultsFromRun:
                output_area.text = 'Workload data loaded successfully.'
            else:
                # Data not loaded yet, start loading if not already started
                if not hasattr(ui, 'resultsFromRun') or ui.resultsFromRun is None:
                    state.load_workload_data()
                # Start polling for completion
                ui.timer(0.5, check_workload_status, once=True)
        else:
            # Still loading, start polling
            ui.timer(0.5, check_workload_status, once=True)




if __name__ in {"__main__", "__mp_main__"}:
    # Allow port to be configured via environment variable for local development
    # Default to 443 for Docker, but allow override (e.g., 8080 for local dev)
    port = int(os.environ.get('PORT', 443))

    # # Configure host - use 127.0.0.1 for local development (browsers can't connect to 0.0.0.0)
    # # Use 0.0.0.0 for Docker/production where external access is needed
    # # Can be explicitly overridden via HOST environment variable
    if port == 443:
        default_host = '0.0.0.0'  # Docker/external access
    else:
        default_host = '127.0.0.1'  # Local development - browsers can connect to this
    host = os.environ.get('HOST', default_host)

    logger.info(f"Starting NiceGUI server on {host}:{port}")

    ui.run(
        title='Referee Mentor System',
        port=443,
        host='0.0.0.0',
        reload=False,
        show=False,
        dark=True,  # Force dark mode exclusively
        favicon=None,  # Explicitly disable favicon to avoid potential WebSocket issues
        storage_secret=os.environ.get('STORAGE_SECRET', 'referee-mentor-secret-key-change-in-production')
    )

