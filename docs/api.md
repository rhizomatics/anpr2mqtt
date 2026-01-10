# API

## DVLA

The United Kingdom's government free [Vehicle Enquiry Service (VES) API](https://developer-portal.driver-vehicle-licensing.api.gov.uk/apis/vehicle-enquiry-service/vehicle-enquiry-service-description.html) for licence lookup is supported directly.

Instructions for obtaining the required API Key and current URL are at the [DVLA Developer Portal](https://developer-portal.driver-vehicle-licensing.api.gov.uk), with the best place to start [FRegister For VES API](https://developer-portal.driver-vehicle-licensing.api.gov.uk/apis/vehicle-enquiry-service/vehicle-enquiry-service-description.html#register-for-ves-api).

Configure the API key using the `DVLA__API_KEY` environment variable, the CLI argument, or in the configuration

```yaml
dvla:
    api_key: 59859j545h458957
    cache_ttl: 86400 # number of seconds to cache the result
```