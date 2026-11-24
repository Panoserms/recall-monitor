// The receipt-to-match story, 10 seconds, loops cleanly (first and last frame are the same empty table).
// Everything shown is MADE UP and says so on screen: the receipt, its lines, the recall and its codes.
// Colours and type are the site's own (recall/web/static/style.css): off-white, dark blue, dashed blue = check your pack.
import { AbsoluteFill, Easing, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig, delayRender, continueRender } from "remotion";
import React, { useEffect, useState } from "react";

const C = { paper: "#f7f6f2", surface: "#ffffff", ink: "#13294b", soft: "#4b5a73", rule: "#d9d7cf", slip: "#fffdf6", table: "#e9e7e0" };
const SANS = "Atkinson, system-ui, sans-serif";
const DOTS = "Doto, monospace";

// made-up receipt lines; the fourth one is the match
const LINES = [
  { printed: "Bananen kg", read: "Bananen", price: "1,19" },
  { printed: "Vollk.Bröt. 6er", read: "Vollkorn Brötchen 6er", price: "1,49" },
  { printed: "Hähn.-Schnitzel", read: "Hähnchen Schnitzel", price: "4,99" },
  { printed: "Erdnüsse gerö.", read: "Erdnüsse geröstet", price: "1,79" },
  { printed: "Joghurt mild", read: "Joghurt mild", price: "0,89" },
];
const MATCH = 3;
const RECALLS = ["Spinat gehackt, tiefgefroren", "Bio Pinienkerne, 100 g", "Erdnüsse geröstet und gesalzen, 200 g", "Basilikum gerebelt", "Weichkäse, 150 g"];

function useFonts() {
  const [handle] = useState(() => delayRender("fonts"));
  useEffect(() => {
    const faces = [
      new FontFace("Atkinson", `url(${staticFile("fonts/AtkinsonHyperlegible-400-latin.woff2")})`, { weight: "400" }),
      new FontFace("Atkinson", `url(${staticFile("fonts/AtkinsonHyperlegible-700-latin.woff2")})`, { weight: "700" }),
      new FontFace("Doto", `url(${staticFile("fonts/Doto-900-latin.woff2")})`, { weight: "900" }),
    ];
    Promise.all(faces.map((f) => f.load())).then((loaded) => { loaded.forEach((f) => (document.fonts as unknown as { add: (face: FontFace) => void }).add(f)); continueRender(handle); });
  }, [handle]);
}

const ease = Easing.bezier(0.2, 0.7, 0.2, 1);
const between = (frame: number, a: number, b: number, from = 0, to = 1) =>
  interpolate(frame, [a, b], [from, to], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });

export const ReceiptStory: React.FC = () => {
  useFonts();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // 0-45: receipt slides onto the table; 45-60: photographed (frame corners close, flash)
  const slipIn = spring({ frame, fps, config: { damping: 18, mass: 0.8 } });
  const shutter = between(frame, 38, 52);
  const flash = interpolate(frame, [52, 55, 66], [0, 0.85, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  // 66-160: lines are read one by one; the scan bar moves down, the review list fills
  const lineAt = (i: number) => 70 + i * 17;
  const scanY = between(frame, 66, lineAt(LINES.length), 0, LINES.length);
  // 160-215: the lines are matched against the recall list
  const listIn = between(frame, 160, 178);
  const sweep = between(frame, 178, 215, 0, RECALLS.length - 1);
  // 215-280: one match lights up; 280-300: everything leaves for the loop
  const hit = between(frame, 215, 232);
  const leave = between(frame, 282, 300);

  return (
    <AbsoluteFill style={{ background: C.table, fontFamily: SANS, color: C.ink, opacity: 1 - leave }}>
      <div style={{ position: "absolute", left: 40, top: 26, fontSize: 22, color: C.soft }}>Made-up example: not a real receipt or recall</div>

      {/* the receipt */}
      <div style={{
        position: "absolute", left: 110, top: 130, width: 400, padding: "28px 26px", background: C.slip,
        boxShadow: "0 2px 10px rgb(19 41 75 / 18%)", transform: `translateY(${(1 - slipIn) * 520}px) rotate(${(1 - slipIn) * -4 - 1.2}deg)`,
      }}>
        <div style={{ textAlign: "center", fontSize: 18, color: C.soft, marginBottom: 14 }}>Beispielmarkt · 12345 Beispielstadt</div>
        {LINES.map((l, i) => (
          <div key={l.printed} style={{ position: "relative", display: "flex", justifyContent: "space-between", fontFamily: DOTS, fontWeight: 900, fontSize: 26,
            letterSpacing: "0.04em", padding: "5px 0", height: 39, boxSizing: "border-box" }}>
            {i === MATCH && <div style={{ position: "absolute", inset: "0 -12px", border: `3px dashed ${C.ink}`, borderRadius: 6, opacity: hit,
              transform: `scale(${0.94 + hit * 0.06})` }} />}
            <span>{l.printed}</span><span>{l.price}</span>
          </div>
        ))}
        <div style={{ borderTop: `2px dashed ${C.rule}`, marginTop: 10, paddingTop: 10, display: "flex", justifyContent: "space-between", fontFamily: DOTS, fontWeight: 900, fontSize: 26 }}>
          <span>zu zahlen</span><span>10,35</span>
        </div>
        {/* scan bar: transform only */}
        <div style={{ position: "absolute", left: 14, right: 14, top: 69, height: 39, background: "rgb(19 41 75 / 10%)", borderLeft: `4px solid ${C.ink}`,
          transform: `translateY(${scanY * 39}px)`, opacity: frame > 66 && frame < lineAt(LINES.length) + 6 ? 1 : 0 }} />
      </div>

      {/* camera corners and flash */}
      {[[0, 0], [1, 0], [0, 1], [1, 1]].map(([x, y]) => (
        <div key={`${x}${y}`} style={{
          position: "absolute", width: 46, height: 46, left: 82 + x * 410, top: 104 + y * 400,
          borderLeft: x ? "none" : `5px solid ${C.ink}`, borderRight: x ? `5px solid ${C.ink}` : "none",
          borderTop: y ? "none" : `5px solid ${C.ink}`, borderBottom: y ? `5px solid ${C.ink}` : "none",
          opacity: interpolate(frame, [20, 38, 60, 70], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
          transform: `translate(${(x ? -1 : 1) * (1 - shutter) * -30}px, ${(y ? -1 : 1) * (1 - shutter) * -30}px)`,
        }} />
      ))}
      <AbsoluteFill style={{ background: "#ffffff", opacity: flash }} />

      {/* right side: first the lines as read, then the recall list */}
      <div style={{ position: "absolute", left: 600, top: 130, width: 620 }}>
        <div style={{ opacity: 1 - listIn, transform: `translateY(${listIn * -20}px)` }}>
          <div style={{ fontSize: 30, fontWeight: 700, marginBottom: 14, opacity: between(frame, 62, 72) }}>Read on your device</div>
          {LINES.map((l, i) => {
            const show = between(frame, lineAt(i), lineAt(i) + 10);
            return (
              <div key={l.read} style={{ display: "flex", gap: 18, alignItems: "baseline", background: C.surface, borderRadius: 8, padding: "10px 16px",
                marginBottom: 8, opacity: show, transform: `translateY(${(1 - show) * 14}px)` }}>
                <span style={{ fontFamily: DOTS, fontWeight: 900, fontSize: 22, width: 240 }}>{l.printed}</span>
                <span style={{ fontSize: 24 }}>{l.read}</span>
              </div>
            );
          })}
        </div>

        <div style={{ position: "absolute", top: 0, left: 0, width: 620, opacity: listIn * (1 - hit * 0.65), transform: `translateY(${(1 - listIn) * 20}px)` }}>
          <div style={{ fontSize: 30, fontWeight: 700, marginBottom: 14 }}>Checked against current recalls</div>
          {RECALLS.map((r, i) => {
            const near = Math.max(0, 1 - Math.abs(sweep - i));
            return (
              <div key={r} style={{ background: C.surface, borderRadius: 8, padding: "12px 16px", marginBottom: 8, fontSize: 24, borderLeft: `6px solid ${C.ink}`,
                opacity: 0.55 + 0.45 * near, transform: `translateX(${near * 12}px)` }}>{r}</div>
            );
          })}
        </div>

        {/* the match */}
        <div style={{ position: "absolute", top: 40, left: 0, width: 620, background: C.surface, borderRadius: 12, padding: "22px 26px",
          borderLeft: `8px dashed ${C.ink}`, boxShadow: "0 6px 22px rgb(19 41 75 / 16%)",
          opacity: hit, transform: `translateY(${(1 - hit) * 40}px) scale(${0.96 + hit * 0.04})` }}>
          <div style={{ fontSize: 22, color: C.soft }}>Your purchase: <b style={{ color: C.ink, fontFamily: DOTS }}>{LINES[MATCH].printed}</b></div>
          <div style={{ fontSize: 32, fontWeight: 700, margin: "8px 0 14px" }}>{RECALLS[2]}</div>
          <div style={{ display: "inline-block", border: `3px dashed ${C.ink}`, borderRadius: 8, padding: "6px 14px", fontSize: 26, fontWeight: 700 }}>
            Possible match: check your pack
          </div>
          <div style={{ display: "flex", gap: 30, marginTop: 18 }}>
            {[["Best before", "03/2027"], ["Batch", "L 2611 A"]].map(([label, code]) => (
              <div key={label}>
                <div style={{ fontSize: 18, color: C.soft }}>{label}</div>
                <div style={{ fontFamily: DOTS, fontWeight: 900, fontSize: 34, letterSpacing: "0.06em", border: `1px solid ${C.rule}`, background: C.paper,
                  padding: "2px 10px", borderRadius: 4, marginTop: 4 }}>{code}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 20, color: C.soft, marginTop: 16 }}>Matched by name only. Only the pack can tell.</div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
