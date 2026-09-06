"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Where the handset says it is.
 *
 * This is half of the location check. The other half is the operator's opinion of where
 * the SIM is, which the backend asks CAMARA for using the position captured here. Two
 * independent sources are harder to fake than one: a browser position can be spoofed
 * with developer tools, and a network position cannot be moved by anyone holding the
 * phone.
 *
 * Refusing is a normal answer, not an error. A bank still has to decide, so the refusal
 * is reported to the backend and scored lightly rather than blocking the customer.
 */

export type LocationStage = "idle" | "asking" | "granted" | "denied" | "unavailable";

export interface DeviceLocation {
  stage: LocationStage;
  latitude: number | null;
  longitude: number | null;
  accuracy: number | null;
  error: string | null;
  request: () => void;
}

export function useDeviceLocation(): DeviceLocation {
  const [stage, setStage] = useState<LocationStage>("idle");
  const [latitude, setLatitude] = useState<number | null>(null);
  const [longitude, setLongitude] = useState<number | null>(null);
  const [accuracy, setAccuracy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const request = useCallback(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setStage("unavailable");
      setError("This browser cannot report a location.");
      return;
    }

    setStage("asking");
    setError(null);

    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLatitude(position.coords.latitude);
        setLongitude(position.coords.longitude);
        setAccuracy(position.coords.accuracy);
        setStage("granted");
      },
      (err) => {
        // Denial and failure are different things and deserve different words. A
        // customer who said no should not be told their phone is broken.
        if (err.code === err.PERMISSION_DENIED) {
          setStage("denied");
          setError("You chose not to share your location.");
        } else if (err.code === err.POSITION_UNAVAILABLE) {
          setStage("unavailable");
          setError("Your device could not work out where it is.");
        } else {
          setStage("unavailable");
          setError("Finding your location took too long.");
        }
      },
      // A fix good enough to compare against a 50km network radius does not need the
      // GPS chip. Allowing a cached position keeps the prompt fast indoors.
      { enableHighAccuracy: false, timeout: 15_000, maximumAge: 120_000 }
    );
  }, []);

  // If the browser already knows the answer, skip the prompt entirely.
  useEffect(() => {
    if (typeof navigator === "undefined" || !navigator.permissions?.query) return;
    let cancelled = false;
    navigator.permissions
      .query({ name: "geolocation" as PermissionName })
      .then((status) => {
        if (!cancelled && status.state === "granted") request();
      })
      .catch(() => {
        // Safari has historically not supported querying this. Falling through to the
        // button is the correct behaviour, not an error worth showing anyone.
      });
    return () => {
      cancelled = true;
    };
  }, [request]);

  return { stage, latitude, longitude, accuracy, error, request };
}
