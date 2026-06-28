"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AdvancedMarker,
  APIProvider,
  InfoWindow,
  Map,
  Pin,
  useMap,
  useMapsLibrary,
} from "@vis.gl/react-google-maps";
import type { MarketOut } from "@/lib/api";

type LatLng = { lat: number; lng: number };

type Props = {
  apiKey: string;
  markets: MarketOut[];
  /**
   * Display name of the currently selected scope, used to focus the map when
   * the filter narrows to a region that has no geocoded markers yet (e.g. while
   * the crawler is still working through that province). Pass district name
   * when a district is selected, else province name, else undefined.
   */
  focusLabel?: string;
  /**
   * When set, clicking the map reports the clicked coordinates — used by the
   * "suggest a new place" flow to drop a pin.
   */
  onMapClick?: (lat: number, lng: number) => void;
  /** A draft pin (e.g. the location being suggested), rendered in accent pink. */
  draftPin?: LatLng | null;
  /**
   * When true, clicking an existing market pin selects it via
   * ``onSelectMarket`` (used by the "update an existing place" flow) in
   * addition to opening its info window.
   */
  selectable?: boolean;
  /** Called with the market a user clicked while ``selectable`` is on. */
  onSelectMarket?: (market: MarketOut) => void;
};

// Center of Turkey (rough geographic centroid near Kırşehir) — used as the
// initial view and as the last-resort fallback.
const TURKEY_CENTER = { lat: 39.0, lng: 35.0 } as const;
const TURKEY_DEFAULT_ZOOM = 6;

export function MarketsMap({
  apiKey,
  markets,
  focusLabel,
  onMapClick,
  draftPin,
  selectable,
  onSelectMarket,
}: Props) {
  const [active, setActive] = useState<MarketOut | null>(null);

  const geocoded = useMemo(
    () => markets.filter((m) => m.latitude !== null && m.longitude !== null),
    [markets],
  );

  if (!apiKey) {
    return (
      <div className="card flex h-[60vh] flex-col items-center justify-center text-center text-ink-muted">
        <p className="max-w-md text-sm">
          Harita için Google Maps API anahtarı gerekli.{" "}
          <code className="rounded bg-surface-muted px-1.5 py-0.5">
            NEXT_PUBLIC_GOOGLE_MAPS_API_KEY
          </code>{" "}
          değerini ayarlayıp sayfayı yenileyin.
        </p>
      </div>
    );
  }

  return (
    <APIProvider apiKey={apiKey}>
      <div className="card overflow-hidden">
        <div className="h-[70vh] w-full">
          <Map
            mapId="markets-map"
            defaultCenter={TURKEY_CENTER}
            defaultZoom={TURKEY_DEFAULT_ZOOM}
            gestureHandling="greedy"
            disableDefaultUI={false}
            onClick={
              onMapClick
                ? (e) => {
                    const ll = e.detail.latLng;
                    if (ll) onMapClick(ll.lat, ll.lng);
                  }
                : undefined
            }
          >
            <MapFocus markets={geocoded} focusLabel={focusLabel} />
            {geocoded.map((m) => (
              <AdvancedMarker
                key={m.id}
                position={{ lat: m.latitude as number, lng: m.longitude as number }}
                onClick={() => {
                  setActive(m);
                  if (selectable) onSelectMarket?.(m);
                }}
              >
                <Pin
                  background={m.market_type === "semt_pazari" ? "#635BFF" : "#00D4FF"}
                  borderColor="#FFFFFF"
                  glyphColor="#FFFFFF"
                />
              </AdvancedMarker>
            ))}
            {draftPin && (
              <AdvancedMarker position={draftPin}>
                <Pin background="#FF7AB6" borderColor="#FFFFFF" glyphColor="#FFFFFF" />
              </AdvancedMarker>
            )}
            {active && active.latitude !== null && active.longitude !== null && (
              <InfoWindow
                position={{ lat: active.latitude, lng: active.longitude }}
                onCloseClick={() => setActive(null)}
              >
                <div className="space-y-1 text-xs">
                  <p className="text-sm font-semibold">{active.name}</p>
                  <p className="text-ink-soft">
                    {active.district}, {active.province}
                  </p>
                  {active.address && <p>{active.address}</p>}
                  {active.day_of_week && (
                    <p className="text-ink-muted">Gün: {active.day_of_week}</p>
                  )}
                </div>
              </InfoWindow>
            )}
          </Map>
        </div>
      </div>
    </APIProvider>
  );
}

/**
 * Keeps the viewport aligned with what the user is looking at.
 *
 * Priority:
 *   1. If there are geocoded markers, fit the viewport to them.
 *   2. Otherwise, if a ``focusLabel`` (district / province name) is supplied,
 *      geocode it with the Google Geocoding API and fit to its administrative
 *      viewport — so the user lands on the right region even while the crawler
 *      is still filling in market pins for it.
 *   3. Last resort: a Turkey-wide default centered near Kırşehir.
 */
function MapFocus({ markets, focusLabel }: { markets: MarketOut[]; focusLabel?: string }) {
  const map = useMap();
  const coreLib = useMapsLibrary("core");
  const geocodingLib = useMapsLibrary("geocoding");

  useEffect(() => {
    if (!map || !coreLib) return;

    if (markets.length === 1) {
      const only = markets[0];
      map.panTo({ lat: only.latitude as number, lng: only.longitude as number });
      map.setZoom(14);
      return;
    }
    if (markets.length > 1) {
      const bounds = new coreLib.LatLngBounds();
      for (const m of markets) {
        bounds.extend({ lat: m.latitude as number, lng: m.longitude as number });
      }
      map.fitBounds(bounds, 64);
      return;
    }

    // No markers — try to focus by name (province / district).
    if (focusLabel && geocodingLib) {
      const geocoder = new geocodingLib.Geocoder();
      let cancelled = false;
      void geocoder
        .geocode({ address: `${focusLabel}, Türkiye` })
        .then(({ results }) => {
          if (cancelled || results.length === 0) return;
          const viewport = results[0].geometry.viewport;
          if (viewport) {
            map.fitBounds(viewport, 64);
          } else {
            map.panTo(results[0].geometry.location);
            map.setZoom(11);
          }
        })
        .catch(() => {
          /* swallow — viewport just stays where it is */
        });
      return () => {
        cancelled = true;
      };
    }

    map.panTo(TURKEY_CENTER);
    map.setZoom(TURKEY_DEFAULT_ZOOM);
  }, [map, coreLib, geocodingLib, markets, focusLabel]);

  return null;
}
