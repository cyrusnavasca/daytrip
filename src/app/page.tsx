import { MapPin, Compass, Clock, DollarSign } from "lucide-react";

export default function Home() {
  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-950 via-blue-950 to-slate-900 text-white">
      {/* Nav */}
      <nav className="border-b border-white/10 px-6 py-4 flex items-center justify-between max-w-7xl mx-auto">
        <div className="flex items-center gap-2">
          <Compass className="w-6 h-6 text-blue-400" />
          <span className="font-semibold text-lg tracking-tight">daytrip</span>
        </div>
        <span className="text-xs text-white/40 border border-white/10 rounded-full px-3 py-1">
          Alpha
        </span>
      </nav>

      {/* Hero */}
      <section className="max-w-4xl mx-auto px-6 pt-24 pb-16 text-center">
        <div className="inline-flex items-center gap-2 text-blue-400 text-sm font-medium mb-6 border border-blue-400/20 bg-blue-400/10 rounded-full px-4 py-1.5">
          <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse" />
          AI-powered itinerary generation
        </div>

        <h1 className="text-5xl sm:text-6xl font-bold tracking-tight mb-6 leading-tight">
          Plan the perfect{" "}
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-cyan-400">
            day trip
          </span>
        </h1>

        <p className="text-white/60 text-lg max-w-2xl mx-auto mb-12">
          Tell us where you want to go, your budget, and your vibe — we&apos;ll
          generate a complete itinerary with local picks, real travel times, and
          community-backed recommendations.
        </p>

        {/* Placeholder input card */}
        <div className="bg-white/5 border border-white/10 rounded-2xl p-6 text-left max-w-2xl mx-auto">
          <p className="text-white/40 text-sm mb-4">Try something like...</p>
          <p className="text-white/80 italic text-lg">
            &quot;Fun solo coastal day trip near Santa Barbara under $100&quot;
          </p>
          <button
            disabled
            className="mt-6 w-full bg-blue-600/60 text-white/50 font-medium py-3 rounded-xl cursor-not-allowed text-sm"
          >
            Coming soon — itinerary generation in Phase 2
          </button>
        </div>
      </section>

      {/* Feature grid */}
      <section className="max-w-4xl mx-auto px-6 pb-24 grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          {
            icon: MapPin,
            title: "Local signal",
            desc: "Reddit threads + Yelp reviews surface real hidden gems",
          },
          {
            icon: Clock,
            title: "Time-aware",
            desc: "Real travel times, opening hours, and pacing built in",
          },
          {
            icon: DollarSign,
            title: "Budget-aware",
            desc: "Keeps your whole day under your target spend",
          },
          {
            icon: Compass,
            title: "Route-optimized",
            desc: "Google Directions orders stops for minimum travel time",
          },
        ].map(({ icon: Icon, title, desc }) => (
          <div
            key={title}
            className="bg-white/5 border border-white/10 rounded-xl p-5"
          >
            <Icon className="w-5 h-5 text-blue-400 mb-3" />
            <h3 className="font-semibold text-sm mb-1">{title}</h3>
            <p className="text-white/50 text-xs leading-relaxed">{desc}</p>
          </div>
        ))}
      </section>
    </main>
  );
}
