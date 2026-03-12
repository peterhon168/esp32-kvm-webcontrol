#include "wifi_manager.h"

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "lwip/ip4_addr.h"

#define TAG "WIFI"

#define WIFI_INIT_DONE_BIT   BIT2
#define NVS_NAMESPACE        "wifi_cache"
#define FAST_CONNECT_TIMEOUT_MS  10000

EventGroupHandle_t wifi_event_group;
static int s_retry_num = 0;
static esp_netif_t *s_sta_netif = NULL;
static bool s_fast_connect = false;

// ── NVS helpers ──────────────────────────────────────────────────

typedef struct {
    uint8_t  bssid[6];
    uint8_t  channel;
    uint32_t ip;
    uint32_t gw;
    uint32_t netmask;
} wifi_cache_t;

static esp_err_t nvs_load_cache(wifi_cache_t *cache)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READONLY, &h);
    if (err != ESP_OK) return err;

    size_t len = sizeof(*cache);
    err = nvs_get_blob(h, "cache", cache, &len);
    nvs_close(h);
    return err;
}

static void nvs_save_cache(const wifi_cache_t *cache)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h) != ESP_OK) return;
    nvs_set_blob(h, "cache", cache, sizeof(*cache));
    nvs_commit(h);
    nvs_close(h);
    ESP_LOGI(TAG, "Saved WiFi cache (ch=%d)", cache->channel);
}

static void nvs_clear_cache(void)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h) != ESP_OK) return;
    nvs_erase_all(h);
    nvs_commit(h);
    nvs_close(h);
    ESP_LOGW(TAG, "WiFi cache cleared");
}

// ── Save current connection params to NVS ────────────────────────

static void save_current_connection(void)
{
    wifi_ap_record_t ap;
    if (esp_wifi_sta_get_ap_info(&ap) != ESP_OK) return;

    esp_netif_ip_info_t ip_info;
    if (esp_netif_get_ip_info(s_sta_netif, &ip_info) != ESP_OK) return;

    wifi_cache_t cache = {
        .channel = ap.primary,
        .ip      = ip_info.ip.addr,
        .gw      = ip_info.gw.addr,
        .netmask = ip_info.netmask.addr,
    };
    memcpy(cache.bssid, ap.bssid, 6);
    nvs_save_cache(&cache);
}

// ── Event handler ────────────────────────────────────────────────

static void event_handler(void *arg, esp_event_base_t event_base,
                           int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(wifi_event_group, WIFI_CONNECTED_BIT);
        xEventGroupSetBits(wifi_event_group, WIFI_DISCONNECTED_BIT);
        s_retry_num++;
        int delay_ms = (s_retry_num < 10) ? (s_retry_num * 1000) : 10000;
        ESP_LOGW(TAG, "Disconnected. Reconnecting in %d ms (attempt %d)...",
                 delay_ms, s_retry_num);
        vTaskDelay(pdMS_TO_TICKS(delay_ms));
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
        s_retry_num = 0;
        xEventGroupClearBits(wifi_event_group, WIFI_DISCONNECTED_BIT);
        xEventGroupSetBits(wifi_event_group, WIFI_CONNECTED_BIT | WIFI_INIT_DONE_BIT);
        save_current_connection();
    }
}

// ── Apply static IP from cache ───────────────────────────────────

static void apply_static_ip(const wifi_cache_t *cache)
{
    esp_netif_dhcpc_stop(s_sta_netif);
    esp_netif_ip_info_t ip_info = {
        .ip.addr      = cache->ip,
        .gw.addr      = cache->gw,
        .netmask.addr = cache->netmask,
    };
    ESP_ERROR_CHECK(esp_netif_set_ip_info(s_sta_netif, &ip_info));
    ESP_LOGI(TAG, "Static IP set: " IPSTR, IP2STR(&ip_info.ip));
}

// ── Restore DHCP ─────────────────────────────────────────────────

static void restore_dhcp(void)
{
    esp_netif_ip_info_t zero = { 0 };
    esp_netif_dhcpc_stop(s_sta_netif);
    esp_netif_set_ip_info(s_sta_netif, &zero);
    esp_netif_dhcpc_start(s_sta_netif);
}

// ── Public API ───────────────────────────────────────────────────

esp_err_t wifi_manager_init(const char *ssid, const char *password)
{
    wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    s_sta_netif = esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, &event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, &event_handler, NULL, NULL));

    wifi_config_t wifi_config = { 0 };
    strncpy((char *)wifi_config.sta.ssid, ssid, sizeof(wifi_config.sta.ssid) - 1);
    strncpy((char *)wifi_config.sta.password, password, sizeof(wifi_config.sta.password) - 1);
    wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_WPA3_PSK;
    wifi_config.sta.sae_pwe_h2e = WPA3_SAE_PWE_BOTH;

    // Try fast reconnect using cached BSSID + channel + static IP
    wifi_cache_t cache;
    s_fast_connect = false;
    if (nvs_load_cache(&cache) == ESP_OK && cache.channel != 0) {
        ESP_LOGI(TAG, "Fast reconnect: ch=%d BSSID=%02x:%02x:%02x:%02x:%02x:%02x",
                 cache.channel,
                 cache.bssid[0], cache.bssid[1], cache.bssid[2],
                 cache.bssid[3], cache.bssid[4], cache.bssid[5]);
        memcpy(wifi_config.sta.bssid, cache.bssid, 6);
        wifi_config.sta.bssid_set = true;
        wifi_config.sta.channel = cache.channel;
        apply_static_ip(&cache);
        s_fast_connect = true;
    }

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "Connecting to '%s'%s...", ssid,
             s_fast_connect ? " (fast reconnect)" : "");

    // Wait for IP with appropriate timeout
    TickType_t timeout = s_fast_connect
        ? pdMS_TO_TICKS(FAST_CONNECT_TIMEOUT_MS)
        : pdMS_TO_TICKS(30000);

    EventBits_t bits = xEventGroupWaitBits(wifi_event_group,
        WIFI_INIT_DONE_BIT, pdFALSE, pdFALSE, timeout);

    if (bits & WIFI_INIT_DONE_BIT) {
        ESP_LOGI(TAG, "WiFi connected");
        return ESP_OK;
    }

    // Fast connect failed — fallback to normal scan
    if (s_fast_connect) {
        ESP_LOGW(TAG, "Fast reconnect failed, falling back to full scan");
        s_fast_connect = false;
        nvs_clear_cache();
        restore_dhcp();

        esp_wifi_disconnect();
        wifi_config.sta.bssid_set = false;
        wifi_config.sta.channel = 0;
        memset(wifi_config.sta.bssid, 0, 6);
        ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
        esp_wifi_connect();

        bits = xEventGroupWaitBits(wifi_event_group,
            WIFI_INIT_DONE_BIT, pdFALSE, pdFALSE, pdMS_TO_TICKS(30000));

        if (bits & WIFI_INIT_DONE_BIT) {
            ESP_LOGI(TAG, "WiFi connected (fallback)");
            return ESP_OK;
        }
    }

    ESP_LOGE(TAG, "WiFi initial connection timed out (will keep retrying in background)");
    return ESP_FAIL;
}
