// ---- Race replay: the year list's top 10 at the end of each month ----
const race = { key: "", frames: null, i: 0, timer: null, rows: new Map(), played: new Set() };
const raceKey = () => `${state.mode}-${state.fmt}`;

function renderRace() {
  const frames = M.year && M.lists?.[state.fmt]?.race;
  stopRace();
  $("race").hidden = !frames?.length;
  if (!frames?.length) { race.key = ""; return; }
  if (race.key === raceKey()) return;
  race.key = raceKey(); race.frames = frames; race.span = null;
  race.rows.forEach((el) => el.remove()); race.rows.clear();
  $("race-axis").innerHTML = "";
  $("race-seek").max = frames.length - 1;
  // One tick per month in the race so far; the slider's own keys and value
  // text cover screen readers, so these are mouse and touch shortcuts.
  const last = Math.max(1, frames.length - 1);
  $("race-ticks").innerHTML = frames.map((f, i) =>
    `<button type="button" tabindex="-1" data-i="${i}" style="left:${(i / last) * 100}%">` +
    `<span class="f">${MON[f.m - 1]}</span><span class="s">${MON[f.m - 1][0]}</span></button>`).join("");
  showFrame(frames.length - 1, false);
}

function monthName(m) { return `${MONTH_FULL[m - 1]} ${M.year}`; }

function showFrame(i, animate = true) {
  const f = race.frames[i], fmtName = LABEL[state.fmt].toLowerCase();
  race.i = i;
  $("race-seek").value = i;
  $("race-seek").setAttribute("aria-valuetext", `Through ${monthName(f.m)}`);
  $("race-ticks").querySelectorAll("button").forEach((b) => b.classList.toggle("on", +b.dataset.i === i));
  $("race-month").textContent = `${MON[f.m - 1]} ${M.year}`;
  const when = i === race.frames.length - 1 ? (M.fraction ?? 1) >= 1 ? " (final)" : " (now)" : "";
  $("race-sub").textContent = f.q
    ? `Top 10 in ${fmtName} at the end of ${monthName(f.m)}: ${f.q} ${f.q === 1 ? "player" : "players"} with ${f.min}+ games${when}`
    : `Nobody had ${f.min} ${fmtName} games by the end of ${monthName(f.m)}${when}`;
  $("race-empty").hidden = f.q > 0;
  const plot = $("race-plot"), anim = animate && !reduced();
  // This month's axis: round steps around the visible TPRs, as many as fit the width.
  // A month nobody qualifies in keeps the previous month's axis.
  const tprs = f.rows.length ? f.rows.map((r) => r[1]) : race.span ?? [2700], a = Math.min(...tprs), b = Math.max(...tprs);
  race.span = [a, b];
  const fit = Math.max(2, Math.floor($("race-axis").clientWidth / 40));
  const step = [25, 50, 100, 200, 250, 500, 1000].find((st) => Math.ceil((b + st / 4) / st) - Math.floor((a - st / 4) / st) <= fit) ?? 1000;
  const lo = Math.floor((a - step / 4) / step) * step, hi = Math.ceil((b + step / 4) / step) * step;
  const pct = (v) => ((v - lo) / (hi - lo)) * 100;
  const axis = $("race-axis"), seen = new Set();
  for (let v = lo; v <= hi; v += step) {
    let t = axis.querySelector(`.t[data-v="${v}"]`);
    if (!t) { t = document.createElement("div"); t.className = "t"; t.dataset.v = v; t.innerHTML = `<span>${v}</span>`; t.style.opacity = 0; t.style.left = `${pct(v)}%`; axis.append(t); }
    seen.add(t);
  }
  axis.querySelectorAll(".t").forEach((t) => {
    const v = +t.dataset.v, inside = seen.has(t);
    t.style.left = `${Math.min(110, Math.max(-10, pct(v)))}%`;
    t.style.opacity = inside ? 1 : 0;
  });
  const keep = new Set();
  f.rows.forEach(([id, tpr, games], rank) => {
    keep.add(id);
    let el = race.rows.get(id);
    const fresh = !el;
    if (fresh) {
      const p = PEOPLE.get(id);
      el = document.createElement("div"); el.className = "race-row";
      el.innerHTML = `<span class="rk"></span><a class="nm" data-player href="/player/${id}#${viewHash()}">${esc(p ? shortName(p.name) : id)}</a><span class="tr"><span class="dt"></span></span><span class="vl"></span>`;
      el.style.opacity = 0; el.style.transform = `translateY(calc(var(--row) * ${rank}))`;
      plot.append(el); race.rows.set(id, el);
      el.querySelector(".dt").style.left = `${pct(tpr)}%`;
      if (anim) el.getBoundingClientRect();
    }
    el.querySelector(".rk").textContent = rank + 1;
    el.querySelector(".vl").innerHTML = `${tpr} <small>${games}g</small>`;
    el.querySelector(".vl").title = `TPR ${tpr} over ${games} games`;
    el.querySelector(".dt").style.left = `${pct(tpr)}%`;
    el.style.transform = `translateY(calc(var(--row) * ${rank}))`;
    el.style.opacity = 1;
  });
  race.rows.forEach((el, id) => {
    if (keep.has(id)) return;
    race.rows.delete(id);
    el.style.opacity = 0; el.style.pointerEvents = "none";
    setTimeout(() => el.remove(), anim ? 500 : 0);
  });
  if (!anim) plot.querySelectorAll(".race-row, .dt, .t").forEach((el) => { el.style.transition = "none"; el.getBoundingClientRect(); el.style.transition = ""; });
  $("race-play").textContent = race.timer ? "Pause" : i === race.frames.length - 1 ? "Replay" : "Play";
}

function playRace() {
  if (!race.frames) return;
  stopRace();
  race.played.add(race.key);
  if (race.i >= race.frames.length - 1) showFrame(0);
  race.timer = setInterval(() => {
    if (race.i >= race.frames.length - 1) return stopRace();
    showFrame(race.i + 1);
  }, 1300);
  $("race-play").textContent = "Pause";
}
function stopRace() {
  if (race.timer) clearInterval(race.timer);
  race.timer = null;
  if (race.frames) $("race-play").textContent = race.i === race.frames.length - 1 ? "Replay" : "Play";
}
$("race-play").addEventListener("click", () => race.timer ? stopRace() : playRace());
$("race-ticks").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-i]");
  if (b) { stopRace(); race.played.add(race.key); showFrame(+b.dataset.i); }
});
$("race-seek").addEventListener("input", (e) => { stopRace(); race.played.add(race.key); showFrame(+e.target.value); });
// The first time a race scrolls into view it plays from January, once per list.
new IntersectionObserver((es) => {
  if (es.some((x) => x.isIntersecting) && race.frames && !race.played.has(race.key) && !reduced() && !$("race").hidden) playRace();
}, { threshold: 0.6 }).observe($("race"));
