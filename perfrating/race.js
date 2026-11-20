// ---- Race replay: a list's top 10 month by month ----
// A year list replays from January, everything so far; the rolling list
// replays its 12-list window at each of the last 12 lists. It opens at rest
// on the latest month and plays when asked.
const race = { key: "", frames: null, i: 0, timer: null, rows: new Map() };
const raceKey = () => `${state.mode}-${state.fmt}`;

function renderRace() {
  const frames = M.lists?.[state.fmt]?.race;
  stopRace();
  $("race").hidden = !frames?.length;
  if (!frames?.length) { race.key = ""; return; }
  if (race.key === raceKey()) return;
  race.key = raceKey(); race.frames = frames; race.span = null;
  race.rows.forEach((el) => el.remove()); race.rows.clear();
  $("race-axis").innerHTML = "";
  $("race-title").textContent = M.year ? "How the race unfolded" : "How the ranking moved";
  $("race-seek").max = frames.length - 1;
  // One tick per month in the race so far; the slider's own keys and value
  // text cover screen readers, so these are mouse and touch shortcuts.
  const last = Math.max(1, frames.length - 1);
  $("race-ticks").style.setProperty("--last", last);
  $("race-ticks").innerHTML = frames.map((f, i) =>
    `<button type="button" tabindex="-1" data-i="${i}" style="left:${(i / last) * 100}%">` +
    `<span class="f">${MON[f.m - 1]}${!M.year && (i === 0 || f.m === 1) ? ` ’${String(f.y).slice(2)}` : ""}</span>` +
    `<span class="s">${MON[f.m - 1][0]}</span></button>`).join("");
  showFrame(frames.length - 1, false);
}

function monthName(f) { return `${MONTH_FULL[f.m - 1]} ${f.y ?? M.year}`; }

function showFrame(i, animate = true) {
  const f = race.frames[i], fmtName = LABEL[state.fmt].toLowerCase();
  race.i = i;
  $("race-tip").hidden = true;
  $("race-seek").value = i;
  $("race-seek").style.setProperty("--p", race.frames.length > 1 ? i / (race.frames.length - 1) : 1);
  $("race-seek").setAttribute("aria-valuetext", M.year ? `Through ${monthName(f)}` : `12 lists to ${monthName(f)}`);
  $("race-ticks").querySelectorAll("button").forEach((b) => b.classList.toggle("on", +b.dataset.i === i));
  $("race-month").textContent = `${MON[f.m - 1]} ${f.y ?? M.year}`;
  const lastFrame = i === race.frames.length - 1;
  $("race-seek").classList.toggle("end", lastFrame);
  const when = !lastFrame ? "" : M.year && (M.fraction ?? 1) >= 1 ? " (final)" : " (now)";
  // A year counts everything since January; the rolling list, the 12 lists up
  // to this one, among the players in today's pool.
  const span = M.year ? `at the end of ${monthName(f)}` : `over the ${M.periods?.length || 12} lists to ${monthName(f)}`;
  const players = (n) => `${n} ${n === 1 ? "player" : "players"}${M.year ? "" : " from today's pool"}`;
  $("race-sub").textContent = f.q
    ? `Top 10 in ${fmtName} ${span}: ${players(f.q)} with ${f.min}+ games${when}`
    : `Nobody had ${f.min} ${fmtName} games ${span}${when}`;
  $("race-empty").hidden = f.q > 0;
  const plot = $("race-plot"), anim = animate && !reduced();
  // This month's axis: round steps around the visible TPRs and FIDE ratings. The range is
  // kept tight (at most eight steps) and only as many ticks are labeled as fit the width.
  // A month nobody qualifies in keeps the previous month's axis.
  const vals = f.rows.length ? f.rows.flatMap((r) => [r[1], r[3]]).filter((v) => v != null) : race.span ?? [2700];
  const a = Math.min(...vals), b = Math.max(...vals);
  race.span = [a, b];
  const fit = Math.max(2, Math.floor($("race-axis").clientWidth / 44));
  const step = [25, 50, 100, 200, 250, 500, 1000].find((st) => Math.ceil((b + st / 4) / st) - Math.floor((a - st / 4) / st) <= 8) ?? 1000;
  const lo = Math.floor((a - step / 4) / step) * step, hi = Math.ceil((b + step / 4) / step) * step;
  const every = Math.ceil(((hi - lo) / step + 1) / fit);
  const pct = (v) => ((v - lo) / (hi - lo)) * 100;
  const axis = $("race-axis"), seen = new Set();
  for (let v = lo, k = 0; v <= hi; v += step, k++) {
    let t = axis.querySelector(`.t[data-v="${v}"]`);
    if (!t) { t = document.createElement("div"); t.className = "t"; t.dataset.v = v; t.innerHTML = `<span>${v}</span>`; t.style.opacity = 0; t.style.left = `${pct(v)}%`; axis.append(t); }
    t.classList.toggle("nolab", k % every !== 0);
    seen.add(t);
  }
  axis.querySelectorAll(".t").forEach((t) => {
    const v = +t.dataset.v, inside = seen.has(t);
    t.style.left = `${Math.min(110, Math.max(-10, pct(v)))}%`;
    t.style.opacity = inside ? 1 : 0;
  });
  const keep = new Set();
  f.rows.forEach(([id, tpr, games, rating], rank) => {
    keep.add(id);
    let el = race.rows.get(id);
    const fresh = !el;
    if (fresh) {
      const p = PEOPLE.get(id);
      el = document.createElement("div"); el.className = "race-row";
      // Full name on wide screens, surname on a phone: the surname is the part to keep.
      el.innerHTML = `<span class="rk"></span><a class="nm" data-player href="/player/${id}#${viewHash()}">` +
        `<span class="f">${esc(p ? shortName(p.name) : id)}</span><span class="s">${esc(p ? surname(p.name) : id)}</span></a>` +
        `<span class="tr"><span class="cn"></span><span class="rt"></span><span class="dt"></span></span><span class="vl"></span>`;
      el.style.opacity = 0; el.style.transform = `translateY(calc(var(--row) * ${rank}))`;
      plot.append(el); race.rows.set(id, el);
      place(el, tpr, rating, pct);
      if (anim) el.getBoundingClientRect();
    }
    el.classList.toggle("lead", rank === 0);
    Object.assign(el.dataset, { rank: rank + 1, tpr, games, rating: rating ?? "" });
    el.querySelector(".rk").textContent = rank + 1;
    el.querySelector(".vl").innerHTML = `${tpr} <small>${games} ${games === 1 ? "game" : "games"}</small>`;
    place(el, tpr, rating, pct);
    el.style.transform = `translateY(calc(var(--row) * ${rank}))`;
    el.style.opacity = 1;
  });
  race.rows.forEach((el, id) => {
    if (keep.has(id)) return;
    race.rows.delete(id);
    el.style.opacity = 0; el.style.pointerEvents = "none";
    setTimeout(() => el.remove(), anim ? 500 : 0);
  });
  if (!anim) plot.querySelectorAll(".race-row, .dt, .rt, .cn, .t").forEach((el) => { el.style.transition = "none"; el.getBoundingClientRect(); el.style.transition = ""; });
  $("race-play").textContent = race.timer ? "Pause" : i === race.frames.length - 1 ? "Replay" : "Play";
}

// A row's marks: solid square at the TPR, outline square at the FIDE rating, a line between.
function place(el, tpr, rating, pct) {
  const dt = el.querySelector(".dt"), rt = el.querySelector(".rt"), cn = el.querySelector(".cn");
  dt.style.left = `${pct(tpr)}%`;
  rt.hidden = cn.hidden = rating == null;
  if (rating == null) return;
  rt.style.left = `${pct(rating)}%`;
  cn.style.left = `${pct(Math.min(tpr, rating))}%`;
  cn.style.width = `${Math.abs(pct(tpr) - pct(rating))}%`;
}

function playRace() {
  if (!race.frames) return;
  stopRace();
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
// On a phone the replay is a single line until this button opens it.
$("race-play").addEventListener("click", () => { $("race").classList.add("open"); race.timer ? stopRace() : playRace(); });
$("race-ticks").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-i]");
  if (b) { stopRace(); showFrame(+b.dataset.i); }
});
$("race-seek").addEventListener("input", (e) => { stopRace(); showFrame(+e.target.value); });
// Pointing at a row spells out what its marks show; on a touch screen, tapping it does,
// and the tip stays until the next tap elsewhere.
function raceTip(e) {
  const row = e.target.closest(".race-row"), tip = $("race-tip");
  if (!row) { tip.hidden = true; return; }
  const { rank, tpr, games, rating } = row.dataset;
  tip.innerHTML = `<b>${rank}. ${esc(row.querySelector(".nm .f").textContent)}</b>` +
    `<div class="row2"><span>TPR</span><span class="num"><strong>${tpr}</strong> · ${games} ${games === "1" ? "game" : "games"}</span></div>` +
    (rating ? `<div class="row2"><span>FIDE rating</span><span class="num">${rating}</span></div>` +
      `<div class="row2"><span>Δ</span><span class="num">${signed(tpr - rating)}</span></div>` : "");
  tip.hidden = false;
  const box = $("race-plot").getBoundingClientRect(), dot = row.querySelector(".dt").getBoundingClientRect(), r = row.getBoundingClientRect();
  let left = dot.right - box.left + 12;
  if (left + tip.offsetWidth > box.width) left = dot.left - box.left - tip.offsetWidth - 12;
  tip.style.left = `${Math.max(0, left)}px`;
  tip.style.top = `${r.top - box.top + r.height / 2 - tip.offsetHeight / 2}px`;
}
$("race-plot").addEventListener("pointermove", raceTip);
$("race-plot").addEventListener("pointerdown", raceTip);
$("race-plot").addEventListener("pointerleave", (e) => { if (e.pointerType !== "touch") $("race-tip").hidden = true; });
document.addEventListener("pointerdown", (e) => { if (!e.target.closest("#race-plot")) $("race-tip").hidden = true; });
