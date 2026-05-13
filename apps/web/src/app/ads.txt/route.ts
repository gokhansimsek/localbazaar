/**
 * Dynamic ``/ads.txt`` route.
 *
 * AdSense crawls ``https://<host>/ads.txt`` to verify that the publisher ID
 * declared on the site matches the AdSense account serving ads. Returning
 * this dynamically (instead of a static ``public/ads.txt``) keeps the file
 * in lock-step with ``NEXT_PUBLIC_ADSENSE_CLIENT_ID`` — change the env var,
 * the file follows.
 *
 * Returns an empty 404-equivalent body when the publisher ID is unset so a
 * preview deploy doesn't lie to AdSense's crawler.
 */

const ADSENSE_CLIENT_ID = process.env.NEXT_PUBLIC_ADSENSE_CLIENT_ID ?? "";

// AdSense's well-known certification authority ID. Same value for every
// publisher; see https://support.google.com/adsense/answer/7532444.
const CERTIFICATION_AUTHORITY_ID = "f08c47fec0942fa0";

export function GET(): Response {
  if (!ADSENSE_CLIENT_ID) {
    return new Response("# ads.txt is not configured yet.\n", {
      status: 200,
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  }
  // The publisher ID in ads.txt is the "pub-..." portion only, with the
  // "ca-" prefix stripped.
  const pubId = ADSENSE_CLIENT_ID.replace(/^ca-/, "");
  const body = `google.com, ${pubId}, DIRECT, ${CERTIFICATION_AUTHORITY_ID}\n`;
  return new Response(body, {
    status: 200,
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
}
