import { ItineraryCard } from "@/components/ItineraryCard";
import { ItineraryMap } from "@/components/ItineraryMap";
import type { Itinerary } from "@/types";

interface TripPageProps {
  params: { id: string };
}

// TODO: fetch saved itinerary from DB by trip ID
async function getTrip(_id: string): Promise<Itinerary | null> {
  return null;
}

export default async function TripPage({ params }: TripPageProps) {
  const itinerary = await getTrip(params.id);

  if (!itinerary) {
    return (
      <main className="flex items-center justify-center min-h-screen">
        <p className="text-gray-500">Trip not found.</p>
      </main>
    );
  }

  return (
    <main className="flex flex-col items-center gap-6 px-4 py-12 max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold">{itinerary.summary}</h1>
      <p className="text-sm text-gray-500">
        Estimated total: ${itinerary.totalEstimatedCost.toFixed(0)}
      </p>
      <ItineraryMap stops={itinerary.stops} />
      <div className="flex flex-col gap-3 w-full">
        {itinerary.stops.map((stop, i) => (
          <ItineraryCard key={i} stop={stop} index={i} />
        ))}
      </div>
    </main>
  );
}
