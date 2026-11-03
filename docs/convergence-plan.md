# Convergence plan

**Status: agreed, in progress. Last updated 2026-11-03.**

This fork is going to stop being a fork. The work here is being merged back into
[`bosch-thermostat`](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component),
the project it came from, and this repository will wind down once that is done.

This document explains why, what it means for you, and what has to happen first.
It is kept current as things move. The current plan, with target dates, is public on
[upstream #607](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/issues/607).
The original agreement is on
[upstream #554](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/issues/554).

---

## If you are a user, this is the part that matters

**Nothing changes today, and there is nothing you need to do.** Keep running what you are
running.

- This fork is **still maintained and still the place to get POINTTAPI / CT200
  support**. Releases continue as normal; [v1.7.0](https://github.com/CaseyRo/ha_bosch/releases/tag/v1.7.0)
  is the current stable release.
- When the time comes to move, **you will not be asked to remove and re-add the
  integration**. That is a hard requirement, not an aspiration. See
  [The hard part](#the-hard-part-nobody-loses-their-entry) below.
- Wind-down will be announced here and in a release, with the migration path
  written down, well before anything is archived.

If any of that turns out not to be possible, this plan changes rather than your
installation breaking.

## Why converge

Two integrations currently claim the Home Assistant `bosch` domain. That has
costs that are not obvious until you hit them:

- **You cannot run both.** Installing one means uninstalling the other, so
  trying the alternative is a disruptive act rather than a cheap experiment.
- **It splits a small community.** Bug reports, testing and translations land in
  one place or the other, and neither gets the full picture.
- **It splits maintenance.** Most issues people file are not POINTTAPI-specific
  at all. They are Home Assistant API changes, translation gaps and deprecations,
  and fixing those twice is wasted effort.

The two projects also have complementary gaps. Upstream has the history, the
users and the Home Assistant standing. This fork has the working cloud path and
people with hardware to test on. Neither is complete alone.

In September 2026 the upstream maintainer proposed merging the efforts and
giving this fork's maintainer commit rights, rather than either project
absorbing the other by force. That offer was accepted, and write access to the
upstream integration and client followed on 18 September. Changes there still go
through pull requests.

## What was agreed

**One integration, maintained together, not two in parallel.** Specifically:

| Piece | Where it ends up |
| --- | --- |
| POINTTAPI transport (HTTP client, OAuth, token refresh) | `bosch-thermostat-client`, the shared library, testable without Home Assistant |
| Home Assistant glue (config flow, entities, coordinator, diagnostics) | The upstream integration |
| A separate `bosch_pointt` domain | **Rejected.** Converging, not formalising the split |

## Where it stands

| Step | State |
| --- | --- |
| **1. Test infrastructure** | **Done.** The client's test suite runs again ([client #72](https://github.com/bosch-thermostat/bosch-thermostat-client-python/pull/72)). The integration has a lint gate ([#584](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/pull/584)), pytest on every push ([#595](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/pull/595)) and Python 3.14 ([#598](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/pull/598)). |
| **2. Config entry migration** | **Merged, not yet released.** [#596](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/pull/596) moves upstream to config entry version 12 and carries this fork's migration chain. See below. |
| **3. Device simulator** | **In review.** alaraun's rawscan-driven simulator ([#591](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/pull/591)) waits on a client release. For the cloud path, the diagnostics files contributors have sent become replay fixtures, where the sender agrees. |
| **4. Transport into the client** | Not started. Target: a client PR in November. |
| **5. Home Assistant glue into the integration** | Not started. Target: five PRs from mid-November, then an upstream beta (0.30.0b1) around 5 December. |
| **6. Parity on real hardware** | Planned for December: CT200 (two zones), Buderus TC100.2 (10 zones, 12 valves), CT200 with radiator valves, room thermostat. |
| **7. Wind-down** | After the holidays: a final release here pointing users upstream, then archiving once the upstream build has run quietly for a few weeks. Target: January 2027. |

The target dates depend on two things this side does not control: upstream
releases (nothing has been released upstream since 11 September) and tester
availability in December. If either slips, the dates move and your installation
stays as it is. Progress is tracked on
[upstream #607](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/issues/607).

## The hard part: nobody loses their entry

This was the genuine blocker, and it is worth stating plainly because it is the
thing most likely to go wrong for users.

Home Assistant 2026.7 added a guard
([core#173184](https://github.com/home-assistant/core/pull/173184)) that refuses
to load a config entry whose version is higher than the integration expects.
This fork writes version 11 after a ten-step migration chain; upstream was at
version 1 with no migrations. Because both use the `bosch` domain, you cannot run
them side by side to ease across, so a CT200 entry would simply not load
upstream.

[#596](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/pull/596)
fixes that on upstream `master`. It moves upstream to version 12 and carries the
whole chain, with every step guarded to POINTTAPI entries, so existing upstream
installations pass through as a plain version bump. An entry this fork wrote now
loads upstream without removing and re-adding the integration.

**That is not enough to switch yet.** Upstream can load your entry, but it does
not speak POINTTAPI until steps 4 and 5 land. Until then a CT200 on upstream
shows "Unknown model". Don't switch early.

Two rules keep the move safe:

- **Identifiers move verbatim.** Entity unique IDs and device identifiers keep
  this fork's exact format, so entity history, dashboards and automations carry
  over. The `11 → 12` migration step stays empty, and this fork never needs to
  write a version 12 entry itself.
- **Only shipped features move.** Work still in progress here (writing away
  events, editing schedules, hybrid heat pumps) stays behind and is proposed
  upstream later on its own.

## What in this repository is temporary

Some of what lives here exists because there was nowhere else to put it. These
are explicitly staging posts, not permanent design decisions:

- **The custom POINTTAPI client and coordinator.** Built inside the integration
  because the shared library did not support the cloud API. Destined for the
  library.
- **The OAuth/PKCE flow and token refresh.** The refresh-and-persist behaviour
  solves the exact gap that stalled the earlier upstream cloud attempts; it moves
  upstream with the transport.
- **The discovery allowlist.** Written for POINTTAPI. The underlying problem,
  asking a device for paths it will refuse, slowly, costs IVT and NEFIT users
  too, but the code does not transfer directly to those connectors.
- **Diagnostics redaction.** A privacy fix that should not be fork-specific.
  The client now masks personal data in raw scans as well
  ([client #73](https://github.com/bosch-thermostat/bosch-thermostat-client-python/pull/73)).
- **CI configuration.** Already sent and merged upstream, see above.

Treat anything in this list as "here for now". If you are building on this
integration, that is the part worth knowing.

## What is not temporary

Bug fixes, releases and support continue here exactly as before until the
handover is real and tested. This is not a frozen repository, and "converging"
is not a euphemism for "abandoned". The
[review cadence](https://github.com/CaseyRo/ha_bosch/issues) is unchanged.

## Open dependencies

- **Upstream releases.** The integration and client have unreleased work on their
  main branches, including the version 12 migration. When and by whom they are
  released is the upstream maintainer's decision, and it is one of the questions
  on [#607](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/issues/607).
- **Ownership after the move.** Who maintains the POINTTAPI path upstream once
  this fork is archived. Also on #607.
- **Relicensing: settled.** This repository is MIT; upstream is Apache-2.0, and
  code moving there has to be Apache-2.0. The POINTTAPI code has two authors, the
  maintainer here and jfhautenauven, and both agreed (jfhautenauven on #554, 27
  September 2026).

## Following along

- The current plan and its open decisions:
  [upstream #607](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/issues/607)
- The original agreement:
  [upstream #554](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/issues/554)
- The migration work:
  [upstream #592](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/issues/592)
  and [#596](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/pull/596)
- Questions about what this means for your installation: open an issue here.
