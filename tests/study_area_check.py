"""Real pointer gestures and completed-search provenance, used by browser_check."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import expect


def check_study_area(page, calls):
    page.locator('#endpoint').fill('https://fixture.test/')
    page.locator('#connect').click()
    expect(page.locator('#search')).to_be_enabled()
    page.locator('#collection').select_option('TEST')
    page.locator('#collection-area').click()
    if page.locator('#edit-area').get_attribute('aria-pressed') == 'false':
        page.locator('#edit-area').click()
    area_js = "Object.values(previewMap._layers).find(l => l.options?.className === 'study-area')"

    def geometry():
        return page.evaluate(f'{area_js}.toGeoJSON(false).geometry')

    def exported():
        with page.expect_download() as download:
            page.locator('#export-query').click()
        return json.loads(Path(download.value.path()).read_text())

    def move(locator, dx, dy):
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        assert box
        x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + dx, y + dy, steps=8)
        page.mouse.up()
        page.wait_for_timeout(80)

    def request_count():
        return len([c for c in calls if urlsplit(c['url']).path == '/search'])

    def bounds(visible):
        longitude, latitude = zip(*visible['coordinates'][0])
        return [min(longitude), min(latitude), max(longitude), max(latitude)]

    def last_query():
        return parse_qs(urlsplit(next(c['url'] for c in reversed(calls) if urlsplit(c['url']).path == '/search')).query)

    def check_rectangle_search(before):
        visible = geometry()
        expected_bbox = bounds(visible)
        assert request_count() == before, 'A rectangle gesture must not search'
        assert list(map(float, page.locator('#bbox').input_value().split(','))) == expected_bbox
        page.locator('#search').click()
        expect(page.locator('#search')).to_be_enabled()
        assert request_count() == before + 1
        assert list(map(float, last_query()['bbox'][0].split(','))) == expected_bbox
        saved = exported()
        assert saved['query']['bbox'] == saved['study_area']['bbox'] == expected_bbox
        assert saved['study_area']['geometry'] == visible
        expect(page.locator('#edit-area')).to_have_attribute('aria-pressed', 'false')
        expect(page.locator('#map .marker-icon')).to_have_count(0)
        page.locator('#edit-area').click()
        expect(page.locator('#map .marker-icon')).to_have_count(4)
        page.locator('#edit-area').click()
        # Native re-selection does not dispatch change; exercise real picker events.
        page.locator('#spatial-mode').click()
        page.keyboard.press('Enter')
        expect(page.locator('#spatial-mode')).to_have_value('bbox')
        expect(page.locator('#map .marker-icon')).to_have_count(4)
        page.locator('#edit-area').click()
        page.locator('#spatial-mode').focus()
        page.keyboard.press('Space')
        page.keyboard.press('Enter')
        expect(page.locator('#map .marker-icon')).to_have_count(4)
        page.locator('#edit-area').click()
        page.locator('#spatial-mode').select_option('none')
        page.locator('#spatial-mode').select_option('bbox')
        expect(page.locator('#edit-area')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('#map .marker-icon')).to_have_count(4)
        assert geometry() == visible and request_count() == before + 1
        assert exported() == saved, 'Resuming editing must retain the completed search export'
        return before + 1

    before = request_count()
    coverage = page.evaluate("Object.values(previewMap._layers).find(l=>l.options?.className==='collection-coverage').toGeoJSON()")
    assert page.evaluate("Object.values(previewMap._layers).filter(l=>l.options?.className==='collection-coverage').every(l=>!l.pm)")
    expect(page.locator('#map .marker-icon')).to_have_count(4)
    old = geometry()
    move(page.locator('#map .study-area'), 30, 18)
    assert geometry() != old, 'Dragging the study body must change coordinates'
    expect(page.locator('#map .marker-icon')).to_have_count(4)
    before = check_rectangle_search(before)
    old = geometry()
    move(page.locator('#map .marker-icon').first, -20, -15)
    assert geometry() != old, 'Dragging a corner must resize the rectangle'
    before = check_rectangle_search(before)
    assert page.evaluate("Object.values(previewMap._layers).find(l=>l.options?.className==='collection-coverage').toGeoJSON()") == coverage
    # Draw cancellation retains the existing area; completing two clicks replaces it.
    old = geometry()
    page.locator('#draw-area').click()
    page.locator('#map').click(position={'x': 140, 'y': 125})
    for mode in ['bbox', 'polygon', 'none']:
        page.locator('#spatial-mode').select_option(mode)
        page.locator('#search').click()
        expect(page.locator('#status')).to_contain_text('Finish or cancel drawing')
        expect(page.locator('#cancel-draw')).to_be_visible()
        assert request_count() == before and geometry() == old
        assert page.evaluate('previewMap.pm.globalDrawModeEnabled()')
    page.locator('#spatial-mode').select_option('bbox')
    page.locator('#cancel-draw').click()
    assert geometry() == old
    # Another network action cancels unfinished drawing and locks every editor.
    pending = []
    page.route('https://fixture.test/page2', lambda route: pending.append(route))
    page.locator('#draw-area').click()
    page.locator('#map').click(position={'x': 140, 'y': 125})
    page.locator('#more').click()
    expect(page.locator('#limit')).to_be_disabled()
    expect(page.locator('#vertices')).to_be_disabled()
    expect(page.locator('#apply-vertices')).to_be_disabled()
    expect(page.locator('#cancel-draw')).to_be_hidden()
    assert not page.evaluate('previewMap.pm.globalDrawModeEnabled()')
    assert geometry() == old
    assert len(pending) == 1
    pending.pop().fallback()
    expect(page.locator('#limit')).to_be_enabled()
    page.unroute('https://fixture.test/page2')
    page.locator('#draw-area').click()
    page.locator('#map').click(position={'x': 130, 'y': 130})
    page.locator('#map').click(position={'x': 320, 'y': 265})
    expect(page.locator('#cancel-draw')).to_be_hidden()
    assert geometry() != old
    expect(page.locator('#map .study-area')).to_have_count(1)
    before = check_rectangle_search(before)
    # Repeated map worlds normalize to WGS84; true date-line crossings roll back.
    page.evaluate('previewMap.setView([0, 190], 5, {animate:false})')
    page.locator('#draw-area').click()
    for latlng in [[-2, 185], [2, 195]]:
        point = page.evaluate('p => {const v=previewMap.latLngToContainerPoint(p); return {x:v.x,y:v.y};}', latlng)
        page.locator('#map').click(position=point)
    expect(page.locator('#status')).to_contain_text('Study rectangle drawn')
    wrapped = bounds(geometry())
    assert -176 < wrapped[0] < -174 and -166 < wrapped[2] < -164, wrapped
    assert page.evaluate(f'previewMap.getBounds().contains({area_js}.getBounds())'), 'The normalized rectangle must remain in view'
    before = check_rectangle_search(before)
    old = geometry()
    page.evaluate('previewMap.setView([0, 180], 5, {animate:false})')
    page.locator('#draw-area').click()
    for latlng in [[-2, 175], [2, 185]]:
        point = page.evaluate('p => {const v=previewMap.latLngToContainerPoint(p); return {x:v.x,y:v.y};}', latlng)
        page.locator('#map').click(position=point)
    expect(page.locator('#status')).to_contain_text('antimeridian')
    assert geometry() == old and request_count() == before
    page.locator('#collection-area').click()
    page.locator('#zoom-area').click()
    # Polygon middle handles insert vertices; vertex handles move and remove them.
    page.locator('#polygon-area').click()
    expect(page.locator('#area-summary')).to_contain_text('Polygon')
    expect(page.locator('#map .marker-icon-middle')).to_have_count(4)
    page.locator('#map .marker-icon-middle').first.click()
    assert len(geometry()['coordinates'][0]) == 6
    old = geometry()
    move(page.locator('#map .marker-icon:not(.marker-icon-middle)').nth(1), 8, -12)
    assert geometry() != old
    page.locator('#map .marker-icon:not(.marker-icon-middle)').nth(1).click(button='right')
    assert len(geometry()['coordinates'][0]) == 5
    # Text input offers the same vertex move/add/remove operations by keyboard/touch.
    page.locator('.coordinate-editor summary').click()
    page.locator('#vertices').fill('30, -1\n33, -1\n33, 3\n31.5, 2\n30, 3')
    page.locator('#apply-vertices').click()
    assert geometry()['coordinates'][0] == [[30, -1], [33, -1], [33, 3], [31.5, 2], [30, 3], [30, -1]]
    valid = geometry()
    page.locator('#vertices').fill('30, -1\n33, 3\n33, -1\n30, 3')
    page.locator('#apply-vertices').click()
    expect(page.locator('#vertices')).to_have_attribute('aria-invalid', 'true')
    assert geometry() == valid
    # A real pointer drag crosses the opposite edge; rollback survives Geoman's event order.
    page.locator('#zoom-area').click()
    handle = page.locator('#map .marker-icon:not(.marker-icon-middle)').first
    handle.scroll_into_view_if_needed()
    target = page.evaluate('() => {const p=previewMap.latLngToContainerPoint([1, 34]); const r=previewMap.getContainer().getBoundingClientRect(); return {x:p.x+r.x,y:p.y+r.y};}')
    box = handle.bounding_box()
    move(handle, target['x'] - box['x'] - box['width'] / 2, target['y'] - box['y'] - box['height'] / 2)
    expect(page.locator('#status')).to_contain_text('Previous valid study area restored')
    assert geometry() == valid
    # Invalid plugin edits are rejected and the previous valid geometry restored.
    page.evaluate(f"() => {{const a={area_js}; a.setLatLngs([[0,0],[2,2],[0,2],[2,0]]); a.fire('pm:edit');}}")
    expect(page.locator('#status')).to_contain_text('Previous valid study area restored')
    assert geometry() == valid
    assert request_count() == before, 'Editing must not send searches'
    bbox = page.locator('#bbox').input_value()
    page.locator('#collection').select_option('OTHER')
    expect(page.locator('#bbox')).to_have_value(bbox)
    assert geometry() == valid
    page.locator('#collection').select_option('TEST')
    page.locator('#zoom-area').click()
    page.locator('#start').fill('2020-01-01')
    page.locator('#end').fill('2020-01-02')
    # Opening/canceling the native picker must not discard polygon vertices.
    page.locator('label[for="spatial-mode"]').click()
    assert geometry() == valid
    page.keyboard.press('Escape')
    page.locator('#spatial-mode').click()
    page.locator('#spatial-mode').click()
    assert geometry() == valid, 'Clicking the control again dismisses rather than confirms'
    page.keyboard.press('Escape')
    # Some browsers parse :open but never match it on a native select.
    page.locator('#spatial-mode').evaluate("el => { const matches = el.matches; el.matches = function(s) { return s === ':open' ? false : matches.call(this, s); }; }")
    page.locator('#spatial-mode').click()
    assert geometry() == valid, 'Opening must be safe without functional :open support'
    page.keyboard.press('Escape')
    page.locator('#spatial-mode').evaluate('el => { delete el.matches; }')
    page.locator('#spatial-mode').click()
    assert geometry() == valid
    page.keyboard.press('Escape')
    assert geometry() == valid
    page.locator('#spatial-mode').focus()
    page.keyboard.press('Space')
    assert geometry() == valid
    page.keyboard.press('ArrowDown')
    page.keyboard.press('Enter')
    expect(page.locator('#spatial-mode')).to_have_value('polygon')
    assert geometry() == valid and request_count() == before
    # Each mode sends exactly one matching spatial filter, preserving other filters.
    for mode in ['polygon', 'bbox', 'none']:
        page.locator('#spatial-mode').select_option(mode)
        assert request_count() == before
        if mode == 'bbox':
            expect(page.locator('#edit-area')).to_have_attribute('aria-pressed', 'true')
            expect(page.locator('#area-summary')).to_contain_text('Rectangle')
            expect(page.locator('#map .marker-icon-middle')).to_have_count(0)
            expect(page.locator('#map .marker-icon')).to_have_count(4)
            assert bounds(geometry()) == bounds(valid), 'Choosing bbox must preserve the polygon envelope'
            assert len(geometry()['coordinates'][0]) == 5
            assert exported() == saved
            rectangle = geometry()
            move(page.locator('#map .study-area'), 12, 8)
            assert geometry() != rectangle, 'Choosing bbox must restore rectangle dragging'
            moved = geometry()
            move(page.locator('#map .marker-icon').first, -8, 7)
            assert geometry() != moved, 'Choosing bbox must restore rectangle resizing'
            valid = geometry()
            assert list(map(float, page.locator('#bbox').input_value().split(','))) == bounds(valid)
            assert request_count() == before and exported() == saved
            assert page.evaluate("Object.values(previewMap._layers).find(l=>l.options?.className==='collection-coverage').toGeoJSON()") == coverage
        page.locator('#search').click()
        expect(page.locator('.result-card')).to_have_count(2)
        expect(page.locator('#search')).to_be_enabled()
        before += 1
        assert request_count() == before
        query = last_query()
        assert ('bbox' in query) == (mode == 'bbox')
        assert ('intersects' in query) == (mode == 'polygon')
        assert query['collections'] == ['TEST'] and 'datetime' in query and query['limit'] == ['25']
        if mode == 'polygon':
            assert json.loads(query['intersects'][0]) == valid
        if mode == 'bbox':
            assert list(map(float, query['bbox'][0].split(','))) == bounds(valid)
        saved = exported()
        assert saved['spatial_mode'] == mode and saved['study_area']['geometry'] == valid
        assert saved['study_area']['bbox'] == bounds(valid)
        if mode == 'bbox':
            assert saved['query']['bbox'] == bounds(valid)
    # Re-selecting bbox also restores a rectangle after local polygon editing.
    page.locator('#spatial-mode').select_option('bbox')
    page.locator('#polygon-area').click()
    page.locator('#map .marker-icon-middle').first.click()
    expect(page.locator('#map .marker-icon-middle')).to_have_count(5)
    envelope = bounds(geometry())
    polygon = geometry()
    page.locator('#spatial-mode').click()
    assert geometry() == polygon
    page.keyboard.press('Enter')
    expect(page.locator('#area-summary')).to_contain_text('Rectangle')
    expect(page.locator('#map .marker-icon-middle')).to_have_count(0)
    expect(page.locator('#map .marker-icon')).to_have_count(4)
    assert bounds(geometry()) == envelope and request_count() == before
    assert exported() == saved
    page.locator('#edit-area').click()
    # Result footprints remain selectable and never get editor handles.
    assert page.evaluate("Object.values(previewMap._layers).filter(l=>l.options?.className==='result-footprint').every(l=>!l.pm)")
    page.locator('#map .result-footprint').first.click()
    expect(page.locator('#metadata')).to_contain_text('synthetic-1')
    page.locator('#bbox').fill('30,-1,33,3')
    page.locator('#spatial-mode').select_option('polygon')
    expect(page.locator('#result-context')).to_contain_text('completed search')
    assert exported() == saved

    def fail(route):
        route.fulfill(status=503, body='{}', content_type='application/json', headers={'Access-Control-Allow-Origin': '*'})

    page.route('https://fixture.test/search?*', fail)
    page.locator('#search').click()
    expect(page.locator('#status')).to_contain_text('HTTP 503')
    assert exported() == saved
    page.unroute('https://fixture.test/search?*', fail)
    # Invalid manual bbox blocks both spatial modes, while unrestricted mode works.
    page.locator('#bbox').fill('180,0,-180,10')
    page.locator('#search').click()
    expect(page.locator('#status')).to_contain_text('Bbox must')
    assert request_count() == before
    page.locator('#spatial-mode').select_option('none')
    page.locator('#search').click()
    expect(page.locator('#search')).to_be_enabled()
    assert request_count() == before + 1
    query = parse_qs(urlsplit(calls[-1]['url']).query)
    assert 'bbox' not in query and 'intersects' not in query
    page.locator('#spatial-mode').select_option('bbox')
    print('Study area pointer, spatial modes, persistence, invalid geometry, and export tests passed', flush=True)
