#include "network_task.h"
#include "protocol.h"
#include "wifi_manager.h"

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/event_groups.h"
#include "lwip/sockets.h"
#include "esp_log.h"

#define TAG "NET"
#define RECV_TIMEOUT_SEC 2

extern QueueHandle_t hid_event_queue;

static int create_udp_socket(void)
{
    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock < 0) {
        ESP_LOGE(TAG, "Failed to create socket: errno %d", errno);
        return -1;
    }

    struct timeval tv = { .tv_sec = RECV_TIMEOUT_SEC, .tv_usec = 0 };
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    struct sockaddr_in addr = {
        .sin_family      = AF_INET,
        .sin_port        = htons(UDP_PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };

    if (bind(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        ESP_LOGE(TAG, "Failed to bind socket: errno %d", errno);
        close(sock);
        return -1;
    }

    return sock;
}

void network_task(void *pvParameters)
{
    (void)pvParameters;

    int sock = -1;
    uint32_t last_seq = 0;
    udp_packet_t pkt;

    while (1) {
        // Wait for WiFi to be connected before opening socket
        if (sock < 0) {
            ESP_LOGI(TAG, "Waiting for WiFi connection...");
            xEventGroupWaitBits(wifi_event_group,
                WIFI_CONNECTED_BIT, pdFALSE, pdFALSE, portMAX_DELAY);

            sock = create_udp_socket();
            if (sock < 0) {
                vTaskDelay(pdMS_TO_TICKS(1000));
                continue;
            }
            ESP_LOGI(TAG, "Listening on UDP port %d", UDP_PORT);
        }

        // Check if WiFi disconnected — close socket and re-create on reconnect
        EventBits_t bits = xEventGroupGetBits(wifi_event_group);
        if (!(bits & WIFI_CONNECTED_BIT)) {
            ESP_LOGW(TAG, "WiFi lost, closing socket");
            close(sock);
            sock = -1;
            continue;
        }

        int len = recvfrom(sock, &pkt, sizeof(pkt), 0, NULL, NULL);

        if (len < 0) {
            // Timeout or error — loop back to check WiFi state
            continue;
        }

        if (len != PACKET_SIZE)            continue;
        if (pkt.magic != PACKET_MAGIC)     continue;

        // Sequence filter (rejects old/duplicate packets)
        if (pkt.sequence <= last_seq
            && (last_seq - pkt.sequence) < 1000) {
            continue;
        }
        last_seq = pkt.sequence;

        hid_event_t event;
        event.type = (event_type_t)pkt.type;

        switch (event.type) {
            case EVENT_TYPE_MOUSE:
                event.mouse.buttons = pkt.mouse.buttons;
                event.mouse.dx      = pkt.mouse.dx;
                event.mouse.dy      = pkt.mouse.dy;
                event.mouse.wheel   = pkt.mouse.wheel;
                event.mouse.pan     = pkt.mouse.pan;
                break;

            case EVENT_TYPE_KEYBOARD:
                event.keyboard.modifiers = pkt.keyboard.modifiers;
                memcpy(event.keyboard.keycodes, pkt.keyboard.keycodes, 6);
                break;

            case EVENT_TYPE_CONSUMER:
                event.consumer.usage_id = pkt.consumer.usage_id;
                break;

            default:
                continue;
        }

        if (xQueueSend(hid_event_queue, &event, 0) != pdTRUE) {
            ESP_LOGW(TAG, "Queue full - dropping event");
        }
    }
}
