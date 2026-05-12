# Dover Bin Collections

Home Assistant custom integration for the Dover resident bin collections portal.
WARNING built by GPT5.5!

## Features
- One date sensor per collection stream discovered for the property
- Attributes for last collection status and completion timestamps
- Dedicated calendar entity for seen collection dates
- Poll interval configurable later through the integration options UI

## Property ID
The integration's configuration requires the Dover portal **point ID** for your property. Dover changed its collections service from the old `collections.dover.gov.uk/property/...` pages to the new `portal.waste.dover.gov.uk` portal and API. Older UPRN-style property IDs may now fail with server errors, so existing users may need to remove and re-add the integration with the new point ID.

To find the current point ID:
1. Open https://portal.waste.dover.gov.uk/recycling-rubbish/property-search
2. Search for and select your property.
3. On the collection-days page, copy the number in the URL after `property-search/` and before `/your-collection-days`.

For example, in:

```text
https://portal.waste.dover.gov.uk/recycling-rubbish/property-search/1234567/your-collection-days
```

the property ID to enter is `1234567`.

## Installation

This folder is structured as a HACS custom integration repository.
