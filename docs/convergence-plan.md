# Convergence plan

**Status: agreed, in progress. Last updated 2026-09-21.**

This fork is going to stop being a fork. The work here is being merged back into
[`bosch-thermostat`](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component),
the project it came from, and this repository will wind down once that is done.

This document explains why, what it means for you, and what has to happen first.
It is kept current as things move — the discussion itself is public on
[upstream issue #554](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/issues/554).

---

## If you are a user, this is the part that matters

**Nothing changes today, and nothing you need to do.** Keep running what you are
running.

- This fork is **still maintained and still the place to get POINTTAPI / CT200
  support**. Releases continue as normal.
- When the time comes to move, **you will not be asked to remove and re-add the
  integration**. That is a hard requirement, not an aspiration — see
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
  at all — they are Home Assistant API changes, translation gaps, deprecations.
  Fixing those twice is wasted effort.

The two projects also have complementary gaps. Upstream has the history, the
users and the Home Assistant standing. This fork has the working cloud path and
people with hardware to test on. Neither is complete alone.

In September 2026 the upstream maintainer proposed merging the efforts and
giving this fork's maintainer commit rights, rather than either project
absorbing the other by force. That offer was accepted, and write access to the
upstream integration followed on 18 September. Changes there still go through
pull requests.

## What was agreed

**One integration, maintained together, not two in parallel.** Specifically:

| Piece | Where it ends up |
| --- | --- |
| POINTTAPI transport (HTTP client, OAuth, token refresh) | `bosch-thermostat-client` — the shared library, testable without Home Assistant |
| Home Assistant glue (config flow, entities, coordinator, diagnostics) | The upstream integration |
| A separate `bosch_pointt` domain | **Rejected.** Converging, not formalising the split |

## The sequence

Deliberately ordered so that nothing user-visible moves before the safety net
exists. No dates: two of the steps depend on other people, and a date this side
cannot control is not a commitment, it is a wish.

**1. Test infrastructure first.** Neither upstream repository ran tests on push.
That is the most likely reason a year of Home Assistant changes broke things
quietly. Two pull requests went up:

- [client-python #72](https://github.com/bosch-thermostat/bosch-thermostat-client-python/pull/72)
  — the test suite could not even be collected; 7 of 9 modules errored before a
  single test ran. Now green on 3.12 and 3.13, waiting for review.
- [integration #584](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/pull/584)
  — that repository has no tests at all, so a lint gate is the only automated
  check currently possible. **Merged 2026-09-19.**

**2. A device simulator.** Upstream has no Bosch hardware to test against. The
fix is to replay recorded devices: feed real captured responses to a local test
server and run a full startup in CI. Every device somebody sends a capture for
then becomes a permanent regression test, and nobody has to own every model.

For the cloud path this needs no new capture mechanism — the coordinator already
caches responses by path, and the diagnostics download contains exactly that. The
dumps contributors have already sent are the starting corpus.

A contributor has since opened a pytest harness for the integration, with a mock
gateway and a raw-scan fixture
([#591](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/pull/591),
the last of a five-PR series). The simulator will build on whatever of that lands.

**3. The transport moves** into the shared library, verified against the
simulator rather than against one maintainer's boiler.

**4. The Home Assistant glue moves**, together with the migration work below.

**5. Parity is confirmed on real hardware** — CT200, Buderus TC100.2, multi-zone
and valve setups — and only then does this repository wind down.

## The hard part: nobody loses their entry

This is the genuine blocker, and it is worth stating plainly because it is the
thing most likely to go wrong for users.

| | This fork | Upstream |
| --- | --- | --- |
| Config entry version | **11** | **1** |
| Migration code | ten-step chain | none |

Home Assistant 2026.7 added a guard
([core#173184](https://github.com/home-assistant/core/pull/173184)) that refuses
to load a config entry whose version is higher than the integration expects.
So today, if you installed upstream over this fork, your entry would not load at
all — and because both use the `bosch` domain, you cannot run them side by side
to ease across.

Converging therefore requires upstream to adopt a higher entry version and carry
this fork's migration chain, guarded so that existing upstream installations
never run through migrations meant for POINTTAPI entries.

Until that exists and is tested, nothing moves. This is tracked as its own piece
of work rather than folded into a code port:
[upstream #592](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/issues/592)
has the step-by-step breakdown and the proposal.

## What in this repository is temporary

Some of what lives here exists because there was nowhere else to put it. These
are explicitly staging posts, not permanent design decisions:

- **The custom POINTTAPI client and coordinator.** Built inside the integration
  because the shared library did not support the cloud API. Destined for the
  library.
- **The OAuth/PKCE flow and token refresh.** The refresh-and-persist behaviour
  solves the exact gap that stalled the upstream cloud attempt; it is offered
  upstream rather than kept here.
- **The discovery allowlist.** Written for POINTTAPI, but the underlying problem
  — asking a device for paths it will refuse, slowly — costs IVT and NEFIT users
  too. The idea belongs upstream even though the code does not transfer directly.
- **Diagnostics redaction.** A privacy fix that should not be fork-specific.
- **The service target definitions.** Already offered upstream as
  [#585](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/issues/585).
- **CI configuration.** Already sent, see above.

Treat anything in this list as "here for now". If you are building on this
integration, that is the part worth knowing.

## What is not temporary

Bug fixes, releases and support continue here exactly as before until the
handover is real and tested. This is not a frozen repository, and "converging"
is not a euphemism for "abandoned". The
[review cadence](https://github.com/CaseyRo/ha_bosch/issues) is unchanged.

## Open dependencies

Relicensing is someone else's decision, and so is when upstream reviews
pull requests. That is why no dates appear above.

- **Relicensing.** This repository is MIT; upstream is Apache-2.0, and code
  moving there has to be Apache-2.0. The maintainer here has agreed for his own
  contributions. Other contributors hold copyright in their own commits and are
  being asked individually — nobody's work moves without their explicit yes.

## Following along

- The agreement and ongoing discussion:
  [upstream #554](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/issues/554)
- Open work upstream:
  [client #72](https://github.com/bosch-thermostat/bosch-thermostat-client-python/pull/72),
  [integration #585](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/issues/585),
  [integration #592](https://github.com/bosch-thermostat/home-assistant-bosch-custom-component/issues/592)
- Questions about what this means for your installation: open an issue here.
