"""Playwright tests for the Deadlock Combat Simulator GUI."""

import pytest
from playwright.sync_api import expect


TABS = [
    "Hero Stats",
    "Bullet Damage",
    "Spirit Damage",
    "Scaling",
    "TTK",
    "Comparison",
    "Rankings",
    "Build",
    "Optimizer",
]


# ── Page load ──────────────────────────────────────────────────────────────


def test_page_title(page):
    """Browser tab title should be set correctly."""
    expect(page).to_have_title("Deadlock Combat Simulator")


def test_header_visible(page):
    """Main heading should be visible on load."""
    heading = page.get_by_text("DEADLOCK COMBAT SIMULATOR")
    expect(heading).to_be_visible()


def test_data_loaded_label(page):
    """Status label should report heroes and items loaded."""
    label = page.get_by_text("heroes,", exact=False)
    expect(label).to_be_visible()
    text = label.text_content()
    assert "heroes" in text and "items" in text


# ── Tabs ───────────────────────────────────────────────────────────────────


def test_all_tabs_present(page):
    """All nine tabs should be rendered in the tab bar."""
    for tab_name in TABS:
        tab = page.get_by_role("tab", name=tab_name)
        expect(tab).to_be_visible()


@pytest.mark.parametrize("tab_name", TABS)
def test_tab_clickable(page, tab_name):
    """Each tab should be clickable without raising an error."""
    tab = page.get_by_role("tab", name=tab_name)
    tab.click()
    page.wait_for_load_state("networkidle")
    # After clicking, the tab should be selected (aria-selected=true)
    expect(tab).to_have_attribute("aria-selected", "true")


# ── Hero Stats tab ─────────────────────────────────────────────────────────


def test_hero_stats_tab_has_select(page):
    """Hero Stats tab should contain a hero selector."""
    page.get_by_role("tab", name="Hero Stats").click()
    page.wait_for_load_state("networkidle")
    # NiceGUI select renders as a q-select / combobox
    hero_select = page.locator("[role='combobox']").first
    expect(hero_select).to_be_visible()


def test_hero_stats_tab_has_table(page):
    """Hero Stats tab should display a stats table after selecting a hero."""
    page.get_by_role("tab", name="Hero Stats").click()
    page.wait_for_load_state("networkidle")
    # A table or list of stat rows should be present
    table = page.locator("table, [role='table']").first
    expect(table).to_be_visible()


# ── Rankings tab ───────────────────────────────────────────────────────────


def test_rankings_tab_renders(page):
    """Rankings tab should render a table with hero data."""
    page.get_by_role("tab", name="Rankings").click()
    page.wait_for_load_state("networkidle")
    table = page.locator("table, [role='table']").first
    expect(table).to_be_visible()


# ── TTK tab ────────────────────────────────────────────────────────────────


def test_ttk_tab_has_selectors(page):
    """TTK tab should have Attacker and Defender hero selectors."""
    page.get_by_role("tab", name="TTK").click()
    page.wait_for_load_state("networkidle")
    # Attacker and Defender labels (may appear multiple times due to select labels)
    expect(page.get_by_text("Attacker").first).to_be_visible()
    expect(page.get_by_text("Defender").first).to_be_visible()
    # Should have at least two comboboxes (one per hero)
    selects = page.locator("[role='combobox']")
    assert selects.count() >= 2


# ── Build tab ──────────────────────────────────────────────────────────────


def test_build_tab_loads_shop(page):
    """Build tab should lazy-load and display the item shop."""
    page.get_by_role("tab", name="Build").click()
    # Shop is lazy-loaded; give it a moment
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    # Expect at least one item image/button to appear
    items = page.locator("img, [role='button']")
    assert items.count() > 0


# ── Comparison tab ─────────────────────────────────────────────────────────


def test_comparison_tab_renders(page):
    """Comparison tab should render without errors."""
    page.get_by_role("tab", name="Comparison").click()
    page.wait_for_load_state("networkidle")
    # Should have at least two hero selectors
    selects = page.locator("[role='combobox']")
    assert selects.count() >= 2
