#ifndef WIFI_MANAGER_H
#define WIFI_MANAGER_H

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

#define WIFI_CONNECTED_BIT  BIT0
#define WIFI_DISCONNECTED_BIT BIT1

/**
 * Event group signalling WiFi state changes.
 * WIFI_CONNECTED_BIT is set when IP is obtained.
 * WIFI_DISCONNECTED_BIT is set on disconnect (cleared on reconnect).
 */
extern EventGroupHandle_t wifi_event_group;

/**
 * Initializes WiFi in STA mode and connects to the given network.
 * Blocks until an IP address is obtained.
 * WiFi will auto-reconnect indefinitely on disconnect.
 *
 * @return ESP_OK if connected, ESP_FAIL on failure
 */
esp_err_t wifi_manager_init(const char *ssid, const char *password);

#endif
