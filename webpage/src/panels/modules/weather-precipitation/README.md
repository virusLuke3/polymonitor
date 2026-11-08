# weather-precipitation

Formal default-enabled view. Owns its body and module-local styles; common shell, size and Runtime are unchanged. [Feature/data contract](../../../../../docs/external-panel-integration.md).

API `/runtime/external/weather-precipitation` is a read-only projection owned by `scripts/api/services/weather_expansion/`. Source identities, original clocks and limitations are returned in the payload; no component timer, fetch, fixture or source URL. Registry and App only compose. Shared domain model validates the response.

Resource key `external:weather-precipitation:v1`; common public cache has a 200,000-character per-entry limit. Fresh/retention settings are explicitly declared in `index.tsx` and the domain owner. Missing or expired data is not zero and failed requests do not turn into successful empty lists.

Visual design follows the corresponding approved design preview: distinctive semantic color, heading hierarchy and body composition. Normal five-column workspace dimensions stay intact. Initial real source reads and local semantic tests precede production screenshot/release acceptance; long-cycle stability is not inferred.
