---
tags:
- DVLA
- API
- VES
---
# API

## DVLA

The United Kingdom's government free [Vehicle Enquiry Service (VES) API](https://developer-portal.driver-vehicle-licensing.api.gov.uk/apis/vehicle-enquiry-service/vehicle-enquiry-service-description.html) for licence lookup is supported directly.

Instructions for obtaining the required API Key and current URL are at the [DVLA Developer Portal](https://developer-portal.driver-vehicle-licensing.api.gov.uk), with the best place to start [Register For VES API](https://developer-portal.driver-vehicle-licensing.api.gov.uk/apis/vehicle-enquiry-service/vehicle-enquiry-service-description.html#register-for-ves-api). They also have a [Postman Collection](https://developer-portal.driver-vehicle-licensing.api.gov.uk/apis/vehicle-enquiry-service/assets/VES-API.postman_collection.json) for debugging and testing.

Configure the API key using the `DVLA__API_KEY` environment variable, the CLI argument, or in the configuration

```yaml
dvla:
    api_key: 59859j545h458957
    cache_ttl: 86400 # number of seconds to cache the result
```

### Example Response

```json
{
  "artEndDate": "2025-02-28",
  "co2Emissions" : 135,
  "colour" : "BLUE",
  "engineCapacity": 2494,
  "fuelType" : "PETROL",
  "make" : "ROVER",
  "markedForExport" : false,
  "monthOfFirstRegistration" : "2004-12",
  "motStatus" : "No details held by DVLA",
  "registrationNumber" : "ABC1234",
  "revenueWeight" : 1640,
  "taxDueDate" : "2007-01-01",
  "taxStatus" : "Untaxed",
  "typeApproval" : "N1",
  "wheelplan" : "NON STANDARD",
  "yearOfManufacture" : 2004,
  "euroStatus": "EURO 6 AD",
  "realDrivingEmissions": "1",
  "dateOfLastV5CIssued": "2016-12-25"
}
```