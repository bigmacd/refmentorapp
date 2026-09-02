#!/usr/bin/env python3
"""
NiceGUI-based Referee Mentor System
Converted from Streamlit version
"""

import logging
from datetime import datetime as dtime
import os

# Create logger for this module
import rmaLogging

from fastapi import Response
from fastapi.staticfiles import StaticFiles
from nicegui import ui, app

from appState import AppState
from calendar_tab import CalendarTab
from excelWriter import getExcelFromText
from mentor_game_selection import MentorGameSelection
from auth_nicegui import render_user_sidebar

logger = logging.getLogger(__name__)

state = AppState(logger, ui)


# Serve static files (PWA manifest, icons)
_static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
if os.path.isdir(_static_dir):
    app.add_static_files('/static', _static_dir)

# @app.get('/_nicegui_ws/health')
# def handle_websocket_health():
#     """Diagnostic endpoint to check WebSocket server status"""
#     import sys
#     is_debug = hasattr(sys, 'gettrace') and sys.gettrace() is not None
#     return {
#         'status': 'ok',
#         'websocket_path': '/_nicegui_ws/socket.io/',
#         'debug_mode': is_debug,
#         'message': 'WebSocket server is running' + (' (debug mode may affect connections)' if is_debug else '')
#     }

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


def current_org_id() -> int:
    """Logged-in user's organization, or default org for background/single-org flows."""
    org_id = state.auth_manager.get_current_organization_id()
    if org_id is not None:
        return org_id
    return state.db.getDefaultOrganizationId()


def render_landing_page():
    """Render the public landing page for unauthenticated visitors.

    Layout mirrors a marketing one-pager flow (sticky nav, full-bleed hero,
    alternating full-width sections, wave dividers, CTA bands) while keeping
    the existing landing content topics.
    """
    ui.dark_mode(False)
    ui.add_head_html('<link rel="manifest" href="/static/manifest.json">')
    ui.add_head_html('''
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&family=Outfit:wght@500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --lp-navy: #0b1f4d;
            --lp-navy-deep: #071536;
            --lp-accent: #2f6fed;
            --lp-sky: #6ec1e4;
            --lp-ink: #12203a;
            --lp-muted: #5b6b86;
            --lp-paper: #f7f9fc;
            --lp-white: #ffffff;
        }
        body, .q-page, .nicegui-content {
            background: var(--lp-paper) !important;
            color: var(--lp-ink);
            font-family: "DM Sans", sans-serif;
        }
        .q-page, .nicegui-content {
            padding: 0 !important;
            max-width: none !important;
        }
        .q-header {
            background: transparent !important;
        }
        .lp-page {
            width: 100%;
            overflow-x: hidden;
        }
        .lp-header {
            background: rgba(255, 255, 255, 0.92) !important;
            backdrop-filter: blur(10px);
            box-shadow: 0 1px 0 rgba(11, 31, 77, 0.08);
            color: var(--lp-ink) !important;
        }
        .lp-brand {
            font-family: "Outfit", sans-serif;
            font-weight: 800;
            font-size: 1.15rem;
            letter-spacing: -0.02em;
            color: var(--lp-navy);
            text-decoration: none;
            line-height: 1.1;
        }
        .lp-brand small {
            display: block;
            font-family: "DM Sans", sans-serif;
            font-weight: 500;
            font-size: 0.7rem;
            color: var(--lp-muted);
            letter-spacing: 0.02em;
        }
        .lp-nav a {
            color: var(--lp-ink);
            text-decoration: none;
            font-weight: 600;
            font-size: 0.95rem;
            padding: 0.4rem 0.75rem;
            border-radius: 0.35rem;
            transition: background 0.2s ease, color 0.2s ease;
        }
        .lp-nav a:hover {
            background: rgba(47, 111, 237, 0.1);
            color: var(--lp-accent);
        }
        .lp-btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0.7rem 1.35rem;
            border-radius: 0.35rem;
            font-weight: 700;
            font-size: 0.95rem;
            text-decoration: none;
            transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
        }
        .lp-btn:hover {
            transform: translateY(-1px);
        }
        .lp-btn-primary {
            background: var(--lp-accent);
            color: white !important;
            box-shadow: 0 8px 20px rgba(47, 111, 237, 0.28);
        }
        .lp-btn-primary:hover {
            background: #1f58d0;
            color: white !important;
        }
        .lp-btn-ghost {
            background: transparent;
            color: white !important;
            border: 2px solid rgba(255, 255, 255, 0.7);
        }
        .lp-btn-ghost:hover {
            background: rgba(255, 255, 255, 0.12);
            color: white !important;
        }
        .lp-btn-outline {
            background: transparent;
            color: var(--lp-navy) !important;
            border: 2px solid var(--lp-navy);
        }
        .lp-btn-outline:hover {
            background: var(--lp-navy);
            color: white !important;
        }
        .lp-hero {
            position: relative;
            min-height: 78vh;
            display: flex;
            align-items: center;
            color: white;
            overflow: hidden;
        }
        .lp-hero-media {
            position: absolute;
            inset: 0;
            z-index: 0;
        }
        .lp-hero-media video {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        .lp-hero-overlay {
            position: absolute;
            inset: 0;
            background: linear-gradient(105deg, rgba(7, 21, 54, 0.88) 0%, rgba(11, 31, 77, 0.72) 48%, rgba(11, 31, 77, 0.45) 100%);
            z-index: 1;
        }
        .lp-hero-inner {
            position: relative;
            z-index: 2;
            width: min(1160px, calc(100% - 2.5rem));
            margin: 0 auto;
            padding: 5.5rem 0 4rem;
        }
        .lp-eyebrow {
            display: inline-block;
            font-size: 0.8rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: var(--lp-sky);
            margin-bottom: 0.85rem;
        }
        .lp-hero h1, .lp-section h2, .lp-band h2, .lp-grid-section h2 {
            font-family: "Outfit", sans-serif;
            font-weight: 800;
            letter-spacing: -0.03em;
            line-height: 1.08;
            margin: 0;
        }
        .lp-hero h1 {
            font-size: clamp(2.4rem, 5vw, 3.75rem);
            max-width: 14ch;
            margin-bottom: 1rem;
        }
        .lp-hero p {
            font-size: 1.15rem;
            line-height: 1.65;
            max-width: 36rem;
            color: rgba(255, 255, 255, 0.88);
            margin: 0 0 1.75rem;
        }
        .lp-cta-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.85rem;
        }
        .lp-section {
            width: 100%;
            padding: 4.5rem 1.25rem;
        }
        .lp-section-inner {
            width: min(1160px, 100%);
            margin: 0 auto;
        }
        .lp-split {
            display: grid;
            grid-template-columns: 1.05fr 1fr;
            gap: 3rem;
            align-items: center;
        }
        .lp-media-frame {
            border-radius: 0.5rem;
            overflow: hidden;
            box-shadow: 0 18px 40px rgba(11, 31, 77, 0.18);
            background: #000;
            aspect-ratio: 16 / 10;
        }
        .lp-media-frame video {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }
        .lp-kicker {
            color: var(--lp-accent);
            font-weight: 700;
            font-size: 0.85rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 0.5rem;
        }
        .lp-section h2 {
            font-size: clamp(1.9rem, 3.5vw, 2.6rem);
            color: var(--lp-navy);
            margin-bottom: 1rem;
        }
        .lp-copy {
            color: var(--lp-muted);
            font-size: 1.05rem;
            line-height: 1.7;
            margin-bottom: 1.25rem;
        }
        .lp-checklist {
            list-style: none;
            padding: 0;
            margin: 0 0 1.5rem;
            display: grid;
            gap: 0.65rem;
        }
        .lp-checklist li {
            position: relative;
            padding-left: 1.7rem;
            color: var(--lp-ink);
            font-weight: 500;
            line-height: 1.45;
        }
        .lp-checklist li::before {
            content: "";
            position: absolute;
            left: 0;
            top: 0.35rem;
            width: 0.9rem;
            height: 0.9rem;
            border-radius: 999px;
            background: rgba(47, 111, 237, 0.15);
            box-shadow: inset 0 0 0 2px var(--lp-accent);
        }
        .lp-checklist li::after {
            content: "";
            position: absolute;
            left: 0.28rem;
            top: 0.52rem;
            width: 0.35rem;
            height: 0.2rem;
            border-left: 2px solid var(--lp-accent);
            border-bottom: 2px solid var(--lp-accent);
            transform: rotate(-45deg);
        }
        .lp-waves {
            background-color: var(--lp-paper);
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='250' height='30' viewBox='0 0 1000 120'%3E%3Cg fill='none' stroke='%23e8eef8' stroke-width='6.6'%3E%3Cpath d='M-500 75c0 0 125-30 250-30S0 75 0 75s125 30 250 30s250-30 250-30s125-30 250-30s250 30 250 30s125 30 250 30s250-30 250-30'/%3E%3Cpath d='M-500 45c0 0 125-30 250-30S0 45 0 45s125 30 250 30s250-30 250-30s125-30 250-30s250 30 250 30s125 30 250 30s250-30 250-30'/%3E%3Cpath d='M-500 105c0 0 125-30 250-30S0 105 0 105s125 30 250 30s250-30 250-30s125-30 250-30s250 30 250 30s125 30 250 30s250-30 250-30'/%3E%3C/g%3E%3C/svg%3E");
            background-attachment: fixed;
        }
        .lp-band {
            position: relative;
            padding: 5rem 1.25rem;
            color: white;
            text-align: center;
            background:
                linear-gradient(180deg, rgba(7, 21, 54, 0.82), rgba(7, 21, 54, 0.88)),
                radial-gradient(circle at 20% 20%, #1e40af, transparent 55%),
                radial-gradient(circle at 80% 80%, #0ea5e9, transparent 45%),
                var(--lp-navy-deep);
            background-attachment: fixed, fixed, fixed, scroll;
        }
        .lp-band-inner {
            width: min(760px, 100%);
            margin: 0 auto;
        }
        .lp-band h2 {
            font-size: clamp(1.9rem, 3.5vw, 2.5rem);
            margin-bottom: 1rem;
            color: white;
        }
        .lp-band p {
            color: rgba(255, 255, 255, 0.86);
            font-size: 1.08rem;
            line-height: 1.7;
            margin: 0 0 1.6rem;
        }
        .lp-grid-section {
            background: var(--lp-navy);
            color: white;
            padding: 4.5rem 1.25rem;
        }
        .lp-grid-section h2 {
            color: white;
            text-align: center;
            margin-bottom: 2.25rem;
            font-size: clamp(1.9rem, 3.5vw, 2.5rem);
        }
        .lp-feature-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 1rem;
            width: min(1160px, 100%);
            margin: 0 auto 2rem;
        }
        .lp-feature {
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 0.5rem;
            padding: 1.5rem 1.15rem;
            text-align: center;
            min-height: 10.5rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 0.75rem;
            transition: transform 0.2s ease, background 0.2s ease;
        }
        .lp-feature:hover {
            transform: translateY(-4px);
            background: rgba(255, 255, 255, 0.1);
        }
        .lp-feature-icon {
            width: 2.5rem;
            height: 2.5rem;
            margin: 0 auto;
            border-radius: 999px;
            display: grid;
            place-items: center;
            background: rgba(110, 193, 228, 0.18);
            color: var(--lp-sky);
            font-size: 1.15rem;
            font-weight: 800;
            font-family: "Outfit", sans-serif;
        }
        .lp-feature h3 {
            font-family: "Outfit", sans-serif;
            font-size: 1.05rem;
            font-weight: 700;
            margin: 0;
            line-height: 1.3;
        }
        .lp-center {
            text-align: center;
        }
        .lp-contact {
            background: var(--lp-navy);
            color: white;
            padding: 2.75rem 1.25rem;
        }
        .lp-contact-inner {
            width: min(1160px, 100%);
            margin: 0 auto;
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: 1.25rem;
        }
        .lp-contact h2 {
            font-family: "Outfit", sans-serif;
            font-size: clamp(1.4rem, 2.5vw, 1.9rem);
            margin: 0;
            font-weight: 700;
        }
        .lp-footer {
            background: var(--lp-navy-deep);
            color: rgba(255, 255, 255, 0.7);
            text-align: center;
            padding: 1.5rem 1rem 2rem;
            font-size: 0.9rem;
        }
        .lp-reveal {
            opacity: 0;
            transform: translateY(28px);
            transition: opacity 0.7s ease, transform 0.7s ease;
        }
        .lp-reveal.is-visible {
            opacity: 1;
            transform: none;
        }
        html {
            scroll-behavior: smooth;
        }
        @media (max-width: 960px) {
            .lp-split,
            .lp-feature-grid {
                grid-template-columns: 1fr 1fr;
            }
            .lp-hero {
                min-height: 70vh;
            }
            .lp-nav-desktop {
                display: none !important;
            }
        }
        @media (max-width: 640px) {
            .lp-feature-grid {
                grid-template-columns: 1fr;
            }
            .lp-hero-inner {
                padding-top: 4.5rem;
            }
            .lp-contact-inner {
                flex-direction: column;
                align-items: flex-start;
            }
        }
    </style>
    ''')

    with ui.header().classes('lp-header items-center px-4 py-3').props('bordered=false'):
        with ui.row().classes('w-full items-center justify-between gap-4').style('max-width: 1160px; margin: 0 auto;'):
            ui.html(
                '<a class="lp-brand" href="#">Referee Mentor System'
                '<small>powered by Swynga LLC</small></a>',
                sanitize=False,
            )
            with ui.row().classes('lp-nav lp-nav-desktop items-center gap-1 flex-wrap'):
                ui.link('About', '#about-us')
                ui.link('Why Us', '#why-choose')
                ui.link('How it Works', '#how-it-works')
                ui.link('Contact', '#contact-us')
            ui.link('Sign In', '/login').classes('lp-btn lp-btn-primary')

    with ui.element('div').classes('lp-page'):
        # Hero — full-bleed media + overlay + CTA group
        with ui.element('section').classes('lp-hero'):
            with ui.element('div').classes('lp-hero-media'):
                ui.html('''
                    <video autoplay muted loop playsinline>
                        <source src="/static/landing.mp4" type="video/mp4">
                    </video>
                ''', sanitize=False)
            ui.element('div').classes('lp-hero-overlay')
            with ui.element('div').classes('lp-hero-inner lp-reveal'):
                ui.html('<h1>Referee Mentor System</h1>', sanitize=False)
                ui.html(
                    '<p>A guided, data-driven interface for referee mentors to capture feedback, '
                    'manage assignments, and track development.</p>',
                    sanitize=False,
                )
                with ui.element('div').classes('lp-cta-row'):
                    ui.link('Sign In', '/login').classes('lp-btn lp-btn-primary')
                    ui.link('Learn More', '#about-us').classes('lp-btn lp-btn-ghost')

        # About — split media / copy (like "We Can Help")
        with ui.element('section').props('id=about-us').classes('lp-section lp-waves'):
            with ui.element('div').classes('lp-section-inner lp-split lp-reveal'):
                with ui.element('div').classes('lp-media-frame'):
                    ui.html('''
                        <video autoplay muted loop playsinline>
                            <source src="/static/small_video.mp4" type="video/mp4">
                        </video>
                    ''', sanitize=False)
                with ui.element('div'):
                    ui.label('What is the Referee Mentor System?').classes('lp-kicker')
                    ui.html('<h2>Built for real mentoring</h2>', sanitize=False)
                    ui.html(
                        '<p class="lp-copy">Swynga LLC created the Referee Mentor System to help mentors '
                        'and referees improve performance through structured feedback, clear assignments, '
                        'and meaningful progress tracking.</p>',
                        sanitize=False,
                    )
                    ui.html('''
                        <ul class="lp-checklist">
                            <li>Structured mentoring with guided report forms and role-specific checklists</li>
                            <li>Scheduling &amp; assignments with workload balancing</li>
                            <li>Insights &amp; exports to measure development over time</li>
                            <li>Privacy &amp; security with role-based access</li>
                        </ul>
                    ''', sanitize=False)
                    ui.html(
                        '<p class="lp-copy">Built in collaboration with referees and mentors — '
                        'lightweight, practical, and focused on real-world improvement.</p>',
                        sanitize=False,
                    )

        # Why choose — centered CTA band
        with ui.element('section').props('id=why-choose').classes('lp-band'):
            with ui.element('div').classes('lp-band-inner lp-reveal'):
                ui.html('<h2>Why choose this tool?</h2>', sanitize=False)
                ui.html(
                    '<p>Designed specifically for referee mentoring, the platform combines reporting, '
                    'scheduling, and workload insights in one polished workspace.</p>',
                    sanitize=False,
                )
                ui.link('Explore How it Works', '#how-it-works').classes('lp-btn lp-btn-ghost')

        # How it works — feature grid (like "Our Services")
        with ui.element('section').props('id=how-it-works').classes('lp-grid-section'):
            ui.html('<h2 class="lp-reveal">How it Works</h2>', sanitize=False)
            with ui.element('div').classes('lp-feature-grid lp-reveal'):
                for num, title in (
                    ('1', 'Select games'),
                    ('2', 'Review performance'),
                    ('3', 'Capture mentoring notes'),
                    ('4', 'Track development'),
                ):
                    with ui.element('div').classes('lp-feature'):
                        ui.label(num).classes('lp-feature-icon')
                        ui.html(f'<h3>{title}</h3>', sanitize=False)
            with ui.element('div').classes('lp-center'):
                ui.html(
                    '<p style="color:rgba(255,255,255,0.8);max-width:40rem;margin:0 auto 1.5rem;'
                    'line-height:1.65;">Select games, review referee performance, and submit mentoring '
                    'notes with a clear workflow.</p>',
                    sanitize=False,
                )
                ui.link('Get Started', '#get-started').classes('lp-btn lp-btn-primary')

        # Get started — second CTA band
        with ui.element('section').props('id=get-started').classes('lp-band'):
            with ui.element('div').classes('lp-band-inner lp-reveal'):
                ui.html('<h2>Get Started</h2>', sanitize=False)
                ui.html(
                    '<p>Sign in to immediately access mentor reports, schedules, and workload tracking.</p>',
                    sanitize=False,
                )
                ui.link('Sign In', '/login').classes('lp-btn lp-btn-primary')

        # Contact strip
        with ui.element('section').props('id=contact-us').classes('lp-contact'):
            with ui.element('div').classes('lp-contact-inner lp-reveal'):
                ui.html('<h2>Questions about the Referee Mentor System?</h2>', sanitize=False)
                with ui.row().classes('gap-3 flex-wrap'):
                    ui.link('Sign In', '/login').classes('lp-btn lp-btn-ghost')
                    ui.link('Learn More', '#about-us').classes('lp-btn lp-btn-primary')

        with ui.element('footer').classes('lp-footer'):
            ui.label(f'© {dtime.now().year} Swynga LLC. All rights reserved.')

    ui.add_body_html('''
    <script>
    (function () {
      const reveal = () => {
        document.querySelectorAll('.lp-reveal').forEach((el) => {
          const rect = el.getBoundingClientRect();
          if (rect.top < window.innerHeight * 0.88) {
            el.classList.add('is-visible');
          }
        });
      };
      window.addEventListener('scroll', reveal, { passive: true });
      window.addEventListener('load', reveal);
      setTimeout(reveal, 50);
    })();
    </script>
    ''')


@ui.page('/')
def main_page():
    # Check authentication FIRST - before ANY UI is created
    is_auth = state.auth_manager.is_authenticated()

    if not is_auth:
        render_landing_page()
        return

    ui.dark_mode(True)

    # Only proceed if authenticated - show loading state first
    org_id = current_org_id()

    # Create a loading overlay that will be shown while data loads
    loading_overlay = ui.column().classes('fixed inset-0 bg-white bg-opacity-90 dark:bg-gray-900 dark:bg-opacity-90 items-center justify-center z-50')
    with loading_overlay:
        ui.spinner(size='xl')
        ui.label('Loading data...').classes('mt-4 text-xl text-gray-700 dark:text-gray-300')

    # Poll for data if background load is still in progress
    def wait_for_background_load():
        # Always check if data is loaded first (background thread might have completed)
        if state.is_data_loaded(org_id):
            # Data is loaded, hide overlay using CSS (most reliable method)
            logger.info("Data loaded, hiding loading overlay")
            loading_overlay.style('display: none !important')
            return

        # If still loading, continue polling
        if state.is_loading():
            logger.debug("Data still loading, will check again in 0.3 seconds")
            ui.timer(0.3, wait_for_background_load, once=True)
            return

        # Not loading and not loaded - try to trigger load for this org
        logger.info("Data not loaded for org %s and not loading, attempting to load...", org_id)
        try:
            state.load_data(organization_id=org_id)
            ui.timer(0.1, wait_for_background_load, once=True)
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            loading_overlay.clear()
            with loading_overlay:
                ui.label('Error loading data').classes('text-red-500 text-xl')
                ui.label(str(e)).classes('text-gray-600 dark:text-gray-400 mt-2')
                ui.button('Retry', on_click=lambda: ui.navigate.reload()).classes('mt-4')

    # Check immediately if data is already loaded for this org
    if state.is_data_loaded(org_id):
        logger.info("Data already loaded for org %s when page rendered, hiding loading overlay", org_id)
        loading_overlay.style('display: none !important')
    else:
        # Ensure background load targets the logged-in org (may differ from startup default)
        if not state.is_loading():
            state._start_background_load(organization_id=org_id)
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

    render_user_sidebar(state.auth_manager)



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
        get_match_data=lambda: (state.all_match_data, state.dates),
        ensure_workload=lambda: state.load_workload_data(organization_id=current_org_id()),
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
    org_id = current_org_id()
    card = ui.card().classes('form-container w-full')
    if not state.is_data_loaded(org_id):
        with card:
            with ui.column().classes('items-center justify-center p-8'):
                ui.spinner(size='lg')
                ui.label('Loading data...').classes('mt-4 text-gray-600')
                ui.label('Checking every few seconds. Data will appear when ready.').classes('text-sm text-gray-500 mt-2')
        def check_loaded():
            if state.is_data_loaded(org_id):
                card.clear()
                _build_mentor_report_form(card)
            else:
                if not state.is_loading():
                    state._start_background_load(organization_id=org_id)
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
        org_id = current_org_id()
        mentors = state.db.getMentors(org_id)
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
                center_name = current_match.get('Center', '--')
                ar1_name = current_match.get('AR1', '--')
                ar2_name = current_match.get('AR2', '--')
                center_cb.text = f"Center: {center_name}"
                ar1_cb.text = f"AR1: {ar1_name}"
                ar2_cb.text = f"AR2: {ar2_name}"

                def _is_assignable(name: str) -> bool:
                    return bool(name) and str(name).strip().lower() not in ('none', '(requested)', '--')

                center_cb.disable() if not _is_assignable(center_name) else center_cb.enable()
                ar1_cb.disable() if not _is_assignable(ar1_name) else ar1_cb.enable()
                ar2_cb.disable() if not _is_assignable(ar2_name) else ar2_cb.enable()
                if not _is_assignable(center_name):
                    center_cb.value = False
                if not _is_assignable(ar1_name):
                    ar1_cb.value = False
                if not _is_assignable(ar2_name):
                    ar2_cb.value = False

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
                    if not ref_name or str(ref_name).strip().lower() in ('none', '(requested)', '--'):
                        ui.notify(f'No valid referee assigned for {positions[i]}', type='warning')
                        continue
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
                        current_match.get('GameID', ''),
                        org_id,
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
    org_id = current_org_id()

    with ui.card().classes('form-container w-full'):
        ui.label('Generate Reports').classes('text-xl font-bold mb-4')

        # Report format
        format_select = ui.radio(['Text', 'Excel'], value='Text').props('inline')

        # Report type
        year_data = state.db.getYears(org_id)
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
                    referees = [' '] + state.db.getRefereesForSelectionBox(org_id)
                    sel = ui.select(referees, label='Select Referee').classes('w-full')
                    sel.on_value_change(lambda: set_selection('referee', sel.value))

                elif report_type.value == 'by mentor':
                    mentors = [' '] + state.db.getMentorsForSelectionBox(org_id)
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
                    data = state.db.produceYearReport(sel_value, org_id)
                elif sel_type == 'week':
                    data = state.db.produceWeekReport(sel_value, org_id)
                elif sel_type == 'referee':
                    data = state.db.produceRefereeReport(sel_value, org_id)
                elif sel_type == 'mentor':
                    data = state.db.produceMentorReport(sel_value, org_id)
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
    org_id = current_org_id()
    org_name = state.auth_manager.get_current_organization_name() or f'Organization {org_id}'

    with ui.card().classes('form-container w-full'):
        ui.label('Current Workload').classes('text-xl font-bold mb-2')
        ui.label(f'Organization: {org_name}').classes('text-sm text-gray-400 mb-4')

        output_area = ui.label('Loading workload data...').classes(
            'w-full whitespace-pre-wrap font-mono text-sm p-4 rounded bg-gray-900'
        )

        def check_workload_status():
            if not state.workload_loading:
                if state.workload_error:
                    output_area.text = f'Error loading workload: {state.workload_error}'
                elif state.workload_output:
                    output_area.text = state.workload_output
                elif ui.resultsFromRun:
                    output_area.text = 'Workload data loaded successfully.'
                else:
                    output_area.text = 'No workload data available'
            else:
                ui.timer(0.5, check_workload_status, once=True)

        cached_org = getattr(ui, 'resultsFromRunOrgId', None)
        needs_load = (
            cached_org != org_id
            or not hasattr(ui, 'resultsFromRun')
            or ui.resultsFromRun is None
        )

        if not state.workload_loading:
            if state.workload_error and not needs_load:
                output_area.text = f'Error loading workload: {state.workload_error}'
            elif state.workload_output and not needs_load:
                output_area.text = state.workload_output
            elif hasattr(ui, 'resultsFromRun') and ui.resultsFromRun and not needs_load:
                output_area.text = state.workload_output or 'Workload data loaded successfully.'
            else:
                state.load_workload_data(organization_id=org_id)
                ui.timer(0.5, check_workload_status, once=True)
        else:
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
        port=port,
        host=host,
        reload=False,
        show=False,
        dark=True,  # Force dark mode exclusively
        favicon=None,  # Explicitly disable favicon to avoid potential WebSocket issues
        storage_secret=os.environ.get('STORAGE_SECRET', 'referee-mentor-secret-key-change-in-production')
    )

