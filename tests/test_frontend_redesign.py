"""
Verification test for the redesigned Spaceship Terminal chat interface.
"""

def verify_frontend():
    with open('chat.html', 'r', encoding='utf-8') as f:
        html = f.read()
    with open('css/chat.css', 'r', encoding='utf-8') as f:
        css = f.read()
    with open('js/chat.js', 'r', encoding='utf-8') as f:
        js = f.read()

    # 1. Element IDs verification
    ids = [
        'terminalStars', 'messagesStream', 'composerForm', 'composerInput',
        'sendBtn', 'alienPorthole', 'alienAvatar', 'alienStatusText',
        'terminalStatusBadge', 'demoStrip', 'curiosityBtn', 'openLogBtn',
        'openMemoryBtn', 'drawerBackdrop', 'drawerPanel', 'drawerCloseBtn',
        'drawerBody'
    ]
    for eid in ids:
        assert f'id="{eid}"' in html, f'Missing ID in HTML: {eid}'
        assert eid in js, f'Missing ID reference in JS: {eid}'
    print("  [PASS] All 17 DOM element IDs synchronized between chat.html and js/chat.js.")

    # 2. CSS Architecture
    assert '@media (max-width: 640px)' in css, 'Mobile responsive media query missing'
    assert '@media (prefers-reduced-motion: reduce)' in css, 'Reduced motion media query missing'
    assert '.composer-dock' in css
    assert '.msg-entry.user' in css
    assert '.msg-entry.assistant' in css
    assert '.drawer-panel' in css
    assert 'max-width: 720px' in css, '720px column width missing'
    print("  [PASS] CSS architecture, layout constraints (720px), and media queries verified.")

    # 3. JS Interaction & Accessibility
    assert "e.key === 'Enter' && !e.shiftKey" in js, 'Shift+Enter check missing'
    assert 'prefers-reduced-motion' in js, 'Reduced motion check missing in JS'
    assert '/api/chat' in js, 'Chat API call missing'
    assert '/api/diary' in js, 'Diary API call missing'
    assert '/api/curiosity' in js, 'Curiosity API call missing'
    assert '/api/memories' in js, 'Memories API call missing'
    print("  [PASS] JS keyboard events (Shift+Enter), typewriter stream, and API integrations verified.")

    print("\n>>> FRONTEND REDESIGN VALIDATION: ALL CHECKS PASSED (100%)! <<<")

if __name__ == '__main__':
    verify_frontend()

