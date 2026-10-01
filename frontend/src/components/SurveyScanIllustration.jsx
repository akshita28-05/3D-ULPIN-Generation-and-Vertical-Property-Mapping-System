/**
 * Animated hero illustration: a real rotating 3D building (pure CSS 3D
 * transforms), a surveyor with a tablet and a total-station, a drone
 * orbiting the building, and 3D ULPIN tags popping in one per floor —
 * a visual summary of the actual pipeline (drone/survey data capture ->
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
        @keyframes vsdOrbit {
          from { transform: rotate(0deg) translateX(100px) rotate(0deg); }
          to   { transform: rotate(360deg) translateX(100px) rotate(-360deg); }
        }
        @keyframes vsdRotor {
          from { transform: scaleX(1); }
          to   { transform: scaleX(0.35); }
        }
        @keyframes vsdTabletGlow {
          0%, 100% { opacity: 0.5; }
          50%      { opacity: 1; }
        }
        .vsd-scene { perspective: 900px; }
        .vsd-orbit-wrap {
          position: absolute; top: 50%; left: 50%;
          width: 0; height: 0;
          animation: vsdOrbit 6s linear infinite;
        }
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
        .vsd-tablet-screen { animation: vsdTabletGlow 1.8s ease-in-out infinite; }
        .vsd-rotor { animation: vsdRotor 0.12s linear infinite alternate; transform-origin: center; }
        .vsd-tag-1 { animation: vsdTagPop 4.8s ease-in-out infinite; animation-delay: 0.1s; }
        .vsd-tag-2 { animation: vsdTagPop 4.8s ease-in-out infinite; animation-delay: 1.3s; }
        .vsd-tag-3 { animation: vsdTagPop 4.8s ease-in-out infinite; animation-delay: 2.5s; }
        .vsd-tag-4 { animation: vsdTagPop 4.8s ease-in-out infinite; animation-delay: 3.7s; }
      `}</style>

      <div className="flex items-center justify-center gap-6 sm:gap-10 flex-wrap">
        {/* surveyor: total-station + tablet, scanning toward the building */}
        <svg viewBox="0 0 130 260" className="w-24 sm:w-28 h-auto flex-shrink-0" role="img" aria-label="Surveyor operating a scanning instrument and tablet">
          {/* tripod + total station */}
          <line x1="70" y1="252" x2="86" y2="195" stroke="#254238" strokeWidth="3" />
          <line x1="102" y1="252" x2="86" y2="195" stroke="#254238" strokeWidth="3" />
          <line x1="86" y1="252" x2="86" y2="195" stroke="#254238" strokeWidth="3" />
          <rect x="78" y="182" width="16" height="14" rx="2" fill="#3E7268" />
          <line className="vsd-beam" x1="92" y1="188" x2="124" y2="155" stroke="#C9A24E" strokeWidth="1.5" strokeDasharray="4 3" />

          {/* worker: hard hat, body, legs */}
          <circle cx="46" cy="166" r="9" fill="#EAE2CC" />
          <path d="M37 162 a9 9 0 0 1 18 0 z" fill="#C9A24E" />
          <rect x="38" y="178" width="16" height="32" rx="6" fill="#2C5B53" />
          <line x1="46" y1="252" x2="38" y2="210" stroke="#2C5B53" strokeWidth="6" strokeLinecap="round" />
          <line x1="46" y1="252" x2="54" y2="210" stroke="#2C5B53" strokeWidth="6" strokeLinecap="round" />

          {/* raised arm holding a tablet */}
          <g className="vsd-arm" style={{ transformOrigin: '52px 186px' }}>
            <line x1="52" y1="186" x2="74" y2="170" stroke="#EAE2CC" strokeWidth="5" strokeLinecap="round" />
            <rect x="68" y="156" width="18" height="24" rx="2" fill="#1A332B" stroke="#C9A24E" strokeWidth="1" />
            <rect className="vsd-tablet-screen" x="71" y="159" width="12" height="14" rx="1" fill="#3E7268" />
          </g>
        </svg>

        {/* rotating 3D building, with a drone orbiting it */}
        <div className="relative">
          <div className="vsd-scene relative">
            <div className="vsd-cube">
              <div className="vsd-face vsd-front" />
              <div className="vsd-face vsd-back" />
              <div className="vsd-face vsd-right" />
              <div className="vsd-face vsd-left" />
              <div className="vsd-top" />
            </div>

            {/* orbiting drone */}
            <div className="vsd-orbit-wrap">
              <svg viewBox="0 0 40 24" className="w-8 h-auto" style={{ position: 'absolute', top: '-12px', left: '-20px' }}>
                <rect x="16" y="9" width="8" height="6" rx="1.5" fill="#C9A24E" />
                <line x1="20" y1="9" x2="20" y2="3" stroke="#876A24" strokeWidth="1" />
                <line x1="20" y1="15" x2="20" y2="21" stroke="#876A24" strokeWidth="1" />
                <line x1="16" y1="12" x2="8" y2="12" stroke="#876A24" strokeWidth="1" />
                <line x1="24" y1="12" x2="32" y2="12" stroke="#876A24" strokeWidth="1" />
                <ellipse className="vsd-rotor" cx="8" cy="12" rx="5" ry="1.4" fill="#EAE2CC" fillOpacity="0.8" />
                <ellipse className="vsd-rotor" cx="32" cy="12" rx="5" ry="1.4" fill="#EAE2CC" fillOpacity="0.8" />
                <ellipse className="vsd-rotor" cx="20" cy="3" rx="5" ry="1.4" fill="#EAE2CC" fillOpacity="0.8" />
                <ellipse className="vsd-rotor" cx="20" cy="21" rx="5" ry="1.4" fill="#EAE2CC" fillOpacity="0.8" />
              </svg>
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