/**
 * Animated hero illustration: a real rotating 3D building (pure CSS 3D
 * transforms — a box built from 4 rotating faces + a top face, so it's an
 * actual 3D object turning in space, not a flat picture), a surveyor
 * beside it, and 3D ULPIN tags popping in one per floor as the system
 * "scans" it — a visual summary of the actual pipeline (data capture ->
 * AI processing -> one 3D ULPIN per floor).
 *
 * Pure inline CSS keyframes + SVG, no external image/animation service —
 * nothing to fetch, nothing that can go offline or get blocked.
 */
export default function SurveyScanIllustration({ className = '' }) {
  return (
    <div className={`relative ${className}`}>
      <style>{`
        @keyframes vsdRotate {
          from { transform: rotateX(-14deg) rotateY(0deg); }
          to   { transform: rotateX(-14deg) rotateY(360deg); }
        }
        @keyframes vsdRing {
          0%, 100% { opacity: 0.25; transform: scaleX(1); }
          50%      { opacity: 0.6;  transform: scaleX(1.08); }
        }
        @keyframes vsdTagPop {
          0%, 100% { opacity: 0; transform: scale(0.6) translateX(-6px); }
          15%, 70% { opacity: 1; transform: scale(1) translateX(0); }
        }
        @keyframes vsdBeam {
          0%, 100% { opacity: 0.25; }
          50%      { opacity: 0.85; }
        }
        @keyframes vsdArm {
          0%, 100% { transform: rotate(-6deg); }
          50%      { transform: rotate(10deg); }
        }
        .vsd-scene { perspective: 900px; }
        .vsd-cube {
          position: relative;
          width: 120px; height: 200px;
          margin: 0 auto;
          transform-style: preserve-3d;
          animation: vsdRotate 9s linear infinite;
        }
        .vsd-face {
          position: absolute; inset: 0;
          background-color: #12251F;
          border: 1px solid rgba(201,162,78,0.45);
          background-image:
            repeating-linear-gradient(0deg, rgba(169,130,47,0.30) 0 12px, transparent 12px 32px),
            repeating-linear-gradient(90deg, rgba(169,130,47,0.30) 0 12px, transparent 12px 32px);
        }
        .vsd-front { transform: translateZ(60px); }
        .vsd-back  { transform: rotateY(180deg) translateZ(60px); }
        .vsd-right { width: 120px; transform: rotateY(90deg) translateZ(60px); }
        .vsd-left  { width: 120px; transform: rotateY(-90deg) translateZ(60px); }
        .vsd-top {
          position: absolute; width: 120px; height: 120px;
          top: 0; left: 0;
          background-color: #1A332B;
          border: 1px solid rgba(201,162,78,0.45);
          transform: rotateX(90deg) translateZ(100px) translateY(-50%);
          transform-origin: top;
        }
        .vsd-ring {
          width: 160px; height: 24px;
          margin: 10px auto 0;
          border-radius: 50%;
          border: 2px solid #C9A24E;
          animation: vsdRing 2.6s ease-in-out infinite;
        }
        .vsd-beam { animation: vsdBeam 2.6s ease-in-out infinite; }
        .vsd-arm { animation: vsdArm 2.2s ease-in-out infinite; transform-origin: 86px 190px; }
        .vsd-tag-1 { animation: vsdTagPop 4.8s ease-in-out infinite; animation-delay: 0.1s; }
        .vsd-tag-2 { animation: vsdTagPop 4.8s ease-in-out infinite; animation-delay: 1.3s; }
        .vsd-tag-3 { animation: vsdTagPop 4.8s ease-in-out infinite; animation-delay: 2.5s; }
        .vsd-tag-4 { animation: vsdTagPop 4.8s ease-in-out infinite; animation-delay: 3.7s; }
      `}</style>

      <div className="flex items-center justify-center gap-6 sm:gap-10 flex-wrap">
        {/* surveyor with a total-station, scanning toward the rotating building */}
        <svg viewBox="0 0 120 260" className="w-20 sm:w-24 h-auto flex-shrink-0" role="img" aria-label="Surveyor operating a scanning instrument">
          <line x1="70" y1="252" x2="86" y2="195" stroke="#254238" strokeWidth="3" />
          <line x1="102" y1="252" x2="86" y2="195" stroke="#254238" strokeWidth="3" />
          <line x1="86" y1="252" x2="86" y2="195" stroke="#254238" strokeWidth="3" />
          <rect x="78" y="182" width="16" height="14" rx="2" fill="#3E7268" />
          <line className="vsd-beam" x1="92" y1="188" x2="116" y2="160" stroke="#C9A24E" strokeWidth="1.5" strokeDasharray="4 3" />
          <circle cx="48" cy="168" r="9" fill="#EAE2CC" />
          <rect x="40" y="178" width="16" height="34" rx="6" fill="#2C5B53" />
          <line x1="48" y1="252" x2="40" y2="212" stroke="#2C5B53" strokeWidth="6" strokeLinecap="round" />
          <line x1="48" y1="252" x2="56" y2="212" stroke="#2C5B53" strokeWidth="6" strokeLinecap="round" />
          <line className="vsd-arm" x1="54" y1="188" x2="82" y2="190" stroke="#EAE2CC" strokeWidth="5" strokeLinecap="round" />
        </svg>

        {/* rotating 3D building */}
        <div>
          <div className="vsd-scene">
            <div className="vsd-cube">
              <div className="vsd-face vsd-front" />
              <div className="vsd-face vsd-back" />
              <div className="vsd-face vsd-right" />
              <div className="vsd-face vsd-left" />
              <div className="vsd-top" />
            </div>
          </div>
          <div className="vsd-ring" />
        </div>

        {/* 3D ULPIN tags, popping in one by one as if being assigned */}
        <div className="flex flex-col gap-2">
          <div className="vsd-tag-1 px-3 py-1.5 rounded-full bg-brand-500 text-[#0B1917] text-xs font-mono font-semibold">B01-F04-U01</div>
          <div className="vsd-tag-2 px-3 py-1.5 rounded-full bg-brand-500 text-[#0B1917] text-xs font-mono font-semibold">B01-F03-U01</div>
          <div className="vsd-tag-3 px-3 py-1.5 rounded-full bg-brand-500 text-[#0B1917] text-xs font-mono font-semibold">B01-F02-U01</div>
          <div className="vsd-tag-4 px-3 py-1.5 rounded-full bg-brand-500 text-[#0B1917] text-xs font-mono font-semibold">B01-F01-U01</div>
        </div>
      </div>
    </div>
  )
}