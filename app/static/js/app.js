// 공통 스크립트: 차트 기본값, 접속 인트로, 스크롤 모션, 점수 링, AI 버튼 상태
(function () {
  if (window.Chart) {
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = "#998d78";
    Chart.defaults.borderColor = "#eee2cb";
    Chart.defaults.plugins.legend.labels.boxWidth = 10;
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.elements.bar.borderRadius = 8;
  }
  // 차트 공통 색: 진한 머스터드 · 연한 옐로 · 코랄 · 세이지 — app.css 토큰과 맞춤
  window.PALETTE = { main: "#9c6b17", light: "#ecc66a", coral: "#d9785f", sage: "#7f9a6a",
                     mainFill: "rgba(196,144,42,.20)", grid: "#f3e9d6", label: "#998d78", labelOn: "#6e4a0f" };

  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // 접속 인트로: 1.4초 뒤 사라지고, 같은 탭에서는 다시 안 보임
  var splash = document.getElementById("splash");
  if (splash) {
    try { sessionStorage.setItem("growly-intro", "1"); } catch (e) {}
    setTimeout(function () {
      splash.classList.add("done");
      setTimeout(function () { splash.remove(); }, 700);
    }, reduce ? 0 : 1400);
  }

  // 화면에 들어오면 섹션이 말랑하게 떠오르고, 점수 링이 차오름
  var grids = document.querySelectorAll(".reveal .grid, .reveal .exp-grid");
  grids.forEach(function (g) {
    Array.prototype.forEach.call(g.children, function (c, i) { c.style.setProperty("--i", Math.min(i, 8)); });
  });
  var targets = document.querySelectorAll(".reveal, .ring");
  if (!("IntersectionObserver" in window) || reduce) {
    targets.forEach(function (t) { t.classList.add("in"); });
  } else {
    var fired = false;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { fired = true; en.target.classList.add("in"); io.unobserve(en.target); }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
    targets.forEach(function (t) { io.observe(t); });
    // 관찰이 동작하지 않는 환경(백그라운드 탭·미리보기 등)에서도 내용이 숨겨진 채 남지 않게:
    // 스크롤 위치로 한 번 더 확인하고, 그래도 안 되면 2.5초 뒤 모두 표시
    function check() {
      var h = window.innerHeight || 800;
      targets.forEach(function (t) {
        if (!t.classList.contains("in") && t.getBoundingClientRect().top < h * 0.92) t.classList.add("in");
      });
    }
    window.addEventListener("scroll", check, { passive: true });
    window.addEventListener("resize", check);
    setTimeout(check, 300);
    setTimeout(function () { if (!fired) targets.forEach(function (t) { t.classList.add("in"); }); else check(); }, 2500);
  }

  // 섹션 바로가기: 지금 보고 있는 섹션을 강조
  var navLinks = document.querySelectorAll(".section-nav a[href^='#']");
  if (navLinks.length && "IntersectionObserver" in window) {
    var byId = {};
    navLinks.forEach(function (a) { byId[a.getAttribute("href").slice(1)] = a; });
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting && byId[en.target.id]) {
          navLinks.forEach(function (a) { a.classList.remove("on"); });
          byId[en.target.id].classList.add("on");
        }
      });
    }, { rootMargin: "-40% 0px -55% 0px" });
    Object.keys(byId).forEach(function (id) { var el = document.getElementById(id); if (el) spy.observe(el); });
  }

  // 오래 걸리는 제출 버튼(data-busy): 누르면 잠그고 진행 문구 표시
  document.querySelectorAll("button[data-busy]").forEach(function (b) {
    if (b.form) b.form.addEventListener("submit", function () { b.disabled = true; b.textContent = b.dataset.busy; });
  });

  // AI 요청은 몇 초~수십 초 걸리므로 버튼을 '작성 중'으로 바꿈
  document.querySelectorAll("[data-ai-form]").forEach(function (f) {
    f.addEventListener("submit", function () {
      var b = f.querySelector("button");
      b.disabled = true;
      b.textContent = "✦ AI가 분석하는 중… (최대 1분)";
    });
  });
})();
