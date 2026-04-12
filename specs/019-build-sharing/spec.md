# Feature Specification: Build Sharing

**Feature Branch**: `019-build-sharing`  
**Created**: 2026-04-12  
**Status**: Draft  

## User Scenarios & Testing

### User Story 1 - Clipboard Build Code (Priority: P1)

As a player who wants to share a build with a friend, I want to copy my build as a compact code string so that they can paste it and load my exact build.

**Why this priority**: Clipboard sharing works everywhere (Discord, Reddit, in-game chat) with zero infrastructure.

**Independent Test**: Create a build, click "Copy Build Code", paste into "Import Build Code" on another session, verify the build loads identically.

**Acceptance Scenarios**:

1. **Given** a build with hero, items, ability upgrades, and boon level, **When** I click "Copy Build Code", **Then** a compact encoded string is copied to the clipboard.
2. **Given** a valid build code on the clipboard, **When** I click "Paste Build Code", **Then** the build is fully restored: hero, all items, ability upgrades, and boon level.
3. **Given** an invalid or corrupted build code, **When** pasted, **Then** a clear error message is shown without crashing.

---

### User Story 2 - Shareable URL (Priority: P2)

As a player sharing a build on a public forum, I want a URL that auto-loads my build when opened so that people can see my build with one click.

**Why this priority**: URL sharing is the standard for web-based tools and enables integration with forums and social media.

**Independent Test**: Generate a URL, open it in a new browser tab, verify the build auto-loads on page open.

**Acceptance Scenarios**:

1. **Given** a build is configured, **When** I click "Share URL", **Then** a URL is generated with the build encoded in query parameters.
2. **Given** a valid build URL, **When** someone opens it in their browser, **Then** the GUI auto-loads the build on page open.
3. **Given** the URL contains an outdated item ID (post-patch), **When** loaded, **Then** unknown items are skipped with a warning and the rest of the build loads.

---

### User Story 3 - Build Code in Saved Builds (Priority: P3)

As a player managing saved builds, I want to see and copy the build code for any saved build so that I can share specific builds from my library.

**Why this priority**: Convenience — sharing directly from the saved builds list without having to first load the build.

**Independent Test**: Open saved builds, click copy icon on a build card, verify a valid build code is copied.

**Acceptance Scenarios**:

1. **Given** a list of saved builds, **When** I click the share icon on a build card, **Then** the build code for that build is copied to the clipboard.

---

### Edge Cases

- What happens when the build code references items that don't exist (removed in a patch)?
- How large can a build code be? (12 items + 4 ability upgrade sets + hero + boons)
- What if the URL exceeds browser URL length limits?
- How does the system handle builds with no hero selected?

## Requirements

### Functional Requirements

- **FR-001**: System MUST encode builds as compact base64 strings containing hero name, item IDs, ability upgrades, and boon level.
- **FR-002**: System MUST provide "Copy Build Code" and "Paste Build Code" buttons in the Build tab.
- **FR-003**: System MUST generate shareable URLs with build state encoded in query parameters.
- **FR-004**: System MUST auto-load builds from URL query parameters on page open.
- **FR-005**: System MUST handle invalid/corrupted codes gracefully with clear error messages.
- **FR-006**: Encoding MUST be deterministic — same build always produces the same code.

### Key Entities

- **BuildCode**: Encoded string containing hero ID, item ID list, ability upgrade map, extra souls.
- **BuildCodec**: Encode/decode functions (stateless, pure).

## Success Criteria

- **SC-001**: Round-trip encode → decode produces identical build state.
- **SC-002**: Build codes are under 200 characters for a full 12-item build.
- **SC-003**: URL sharing works across different browsers and sessions.
