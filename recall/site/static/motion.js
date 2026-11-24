// Recall Monitor: interface motion. No library: the Web Animations API, plus a CSS rule for cross-page View Transitions.
// Every animation moves only transform and opacity, says what changed, and is skipped when the visitor asks for
// reduced motion (then state changes are instant). The pages work the same without this file.
(() => {
  "use strict";
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const calm = () => reduced.matches;
  const EASE = "cubic-bezier(0.2, 0.7, 0.2, 1)";

  // something new arrives: from slightly below, fading in; several things one after another
  function arrive(elements, { stagger = 45, distance = 10, duration = 220 } = {}) {
    if (calm()) return;
    [...elements].forEach((el, i) => el.animate(
      [{ opacity: 0, transform: `translateY(${distance}px)` }, { opacity: 1, transform: "none" }],
      { duration, delay: Math.min(i, 8) * stagger, easing: EASE, fill: "backwards" }));
  }

  // something changed in place: a short dip and return, so the eye catches it without anything moving away
  function changed(el) {
    if (calm() || !el) return;
    el.animate([{ opacity: 0.35 }, { opacity: 1 }], { duration: 260, easing: "ease-out" });
  }

  // ------------------------------------------------------- receipt page
  document.addEventListener("recall:results", (event) => {
    const box = document.getElementById("results");
    if (!box) return;
    if (event.detail.first) {
      arrive(box.querySelectorAll("#result-lead, .lead__sub, .alerts > .alert, details.possible"), { stagger: 70, distance: 14 });
    } else {
      changed(document.getElementById("result-lead"));
      arrive(box.querySelectorAll(".alerts > .alert"), { stagger: 30, distance: 6, duration: 180 });
    }
  });

  // the lines of a newly read receipt come in one by one, top to bottom, like a till printing them
  const lines = document.getElementById("lines");
  if (lines) {
    new MutationObserver((records) => {
      const added = records.flatMap((r) => [...r.addedNodes]).filter((n) => n.nodeType === 1 && n.matches(".slip-line"));
      if (added.length > 1) arrive(added, { stagger: 35, distance: 8, duration: 200 });
    }).observe(lines, { childList: true });
    // a corrected line: its note ("Changed by you") appears where the eye is
    lines.addEventListener("input", (event) => {
      const row = event.target.closest(".slip-line");
      const flag = row && row.querySelector("[data-flag]");
      if (flag && flag.dataset.shown !== flag.textContent) { flag.dataset.shown = flag.textContent; changed(flag); }
    });
  }
  document.addEventListener("recall:line-added", (event) => arrive([event.detail.row], { distance: 6 }));
  document.addEventListener("recall:line-removed", (event) => {
    const row = event.detail.row;
    if (calm()) return; // receipt-page.js removes it at once
    row.dataset.leaving = "1";
    row.style.pointerEvents = "none";
    row.animate([{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateX(-24px)" }], { duration: 180, easing: "ease-in" })
      .finished.then(() => row.remove(), () => row.remove());
  });

  // ----------------------------------------------- your alerts, verdicts
  for (const id of ["mine", "my-verdicts", "check-results"]) {
    const box = document.getElementById(id);
    if (!box) continue;
    new MutationObserver(() => arrive(box.querySelectorAll(".alert, .verdict, .result, .lead"), { stagger: 50 }))
      .observe(box, { childList: true });
  }

  // ------------------------------------------------------- story video
  // Plays only while on screen, never when reduced motion is asked for, and always has a visible pause button.
  document.querySelectorAll("[data-story]").forEach((figure) => {
    const video = figure.querySelector("video"), button = figure.querySelector("[data-story-toggle]");
    if (!video || !button) return;
    let wanted = !calm(); // what the visitor wants: playing, unless they paused it or ask for less motion
    const label = () => {
      button.textContent = video.paused ? "Play the example" : "Pause";
      button.setAttribute("aria-pressed", String(!video.paused));
    };
    const visible = { now: false };
    const sync = () => {
      if (wanted && visible.now) video.play().catch(() => { wanted = false; label(); });
      else video.pause();
    };
    video.addEventListener("play", label);
    video.addEventListener("pause", label);
    button.addEventListener("click", () => { wanted = video.paused; sync(); label(); });
    reduced.addEventListener("change", () => { if (calm()) { wanted = false; sync(); } });
    new IntersectionObserver(([entry]) => { visible.now = entry.isIntersecting; sync(); }, { threshold: 0.35 }).observe(video);
    label();
  });
})();
