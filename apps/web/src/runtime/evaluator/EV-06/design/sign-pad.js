/* 서명 칸 (시안용). EV-06 개인 서명 · EV-07 위원장 서명이 같이 씀.
   SignPad.mount(canvas, {onChange(hasInk)}) → {clear(), hasInk(), toDataURL()} */
(function () {
  function mount(canvas, opt) {
    opt = opt || {};
    var ctx = canvas.getContext('2d'), ink = false, drawing = false, last = null;
    function fit() {
      var r = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      if (!r.width) return;
      var keep = ink ? canvas.toDataURL() : null;
      canvas.width = Math.round(r.width * dpr); canvas.height = Math.round(r.height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.lineWidth = 2.6; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.strokeStyle = '#1e2124';
      if (keep) { var im = new Image(); im.onload = function () { ctx.drawImage(im, 0, 0, r.width, r.height); }; im.src = keep; }
    }
    function pos(e) { var r = canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }
    function set(v) { if (ink !== v) { ink = v; opt.onChange && opt.onChange(v); } }
    canvas.addEventListener('pointerdown', function (e) {
      drawing = true; last = pos(e); canvas.setPointerCapture(e.pointerId);
      ctx.beginPath(); ctx.arc(last.x, last.y, 1.3, 0, 6.3); ctx.fillStyle = '#1e2124'; ctx.fill(); set(true); e.preventDefault();
    });
    canvas.addEventListener('pointermove', function (e) {
      if (!drawing) return; var p = pos(e);
      ctx.beginPath(); ctx.moveTo(last.x, last.y); ctx.lineTo(p.x, p.y); ctx.stroke(); last = p;
    });
    function up() { drawing = false; }
    canvas.addEventListener('pointerup', up); canvas.addEventListener('pointercancel', up);
    fit(); window.addEventListener('resize', fit);
    return {
      fit: fit,
      clear: function () { var r = canvas.getBoundingClientRect(); ctx.clearRect(0, 0, r.width, r.height); set(false); },
      hasInk: function () { return ink; },
      /* 시안 확인용: 손으로 쓴 것처럼 그려 넣기 */
      demo: function () {
        var r = canvas.getBoundingClientRect(), w = r.width, h = r.height; ctx.beginPath();
        ctx.moveTo(w * .12, h * .62);
        ctx.bezierCurveTo(w * .2, h * .1, w * .26, h * .9, w * .34, h * .45);
        ctx.bezierCurveTo(w * .4, h * .15, w * .46, h * .8, w * .55, h * .5);
        ctx.bezierCurveTo(w * .62, h * .2, w * .7, h * .85, w * .86, h * .38);
        ctx.stroke(); set(true);
      }
    };
  }
  window.SignPad = { mount: mount };
})();
