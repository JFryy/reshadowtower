/* Exercises the patched framework memcard.c against real files in argv[1]. */
#include "memcard.c"

#define T(x) do { if (!(x)) { fprintf(stderr, "FAIL: %s (line %d)\n", #x, __LINE__); return 1; } } while (0)

static long file_size(const char* path) {
    FILE* f = fopen(path, "rb");
    if (!f) return -1;
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fclose(f);
    return size;
}

static int file_byte(const char* path, long offset) {
    FILE* f = fopen(path, "rb");
    if (!f) return -1;
    fseek(f, offset, SEEK_SET);
    int c = fgetc(f);
    fclose(f);
    return c;
}

static int write_bytes(const char* path, const char* text) {
    FILE* f = fopen(path, "wb");
    if (!f) return -1;
    fputs(text, f);
    return fclose(f);
}

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const char* dir = argv[1];
    char card1[600], card2[600], tmp1[700], bak1[700], bad[600];
    snprintf(card1, sizeof(card1), "%s/card1.mcd", dir);
    snprintf(card2, sizeof(card2), "%s/card2.mcd", dir);
    snprintf(tmp1, sizeof(tmp1), "%s.tmp", card1);
    snprintf(bak1, sizeof(bak1), "%s.bak", card1);
    snprintf(bad, sizeof(bad), "%s/not-a-dir", dir);

    /* card1 exists from an earlier session; the missing card2 is created
     * blank through the temp file. */
    T(memcard_format_file(card1) == 0);
    memcard_init(dir);
    T(memcard_is_present(0) && memcard_is_present(1));
    T(file_size(card2) == MEMCARD_SIZE);
    T(file_byte(card2, 0) == 'M');
    T(file_size(tmp1) == -1);

    /* First flush of a session keeps the previous card as .bak. */
    uint8_t sector[MEMCARD_SECTOR_SIZE];
    memset(sector, 0x5A, sizeof(sector));
    T(memcard_write_sector(0, 100, sector) == 0);
    memcard_flush(0);
    T(file_byte(card1, 100 * MEMCARD_SECTOR_SIZE) == 0x5A);
    T(file_byte(bak1, 100 * MEMCARD_SECTOR_SIZE) == 0xFF);
    T(file_size(tmp1) == -1);

    /* Later flushes in the same session leave the .bak alone. */
    memset(sector, 0x33, sizeof(sector));
    T(memcard_write_sector(0, 100, sector) == 0);
    memcard_flush(0);
    T(file_byte(card1, 100 * MEMCARD_SECTOR_SIZE) == 0x33);
    T(file_byte(bak1, 100 * MEMCARD_SECTOR_SIZE) == 0xFF);

    /* A failed save stays dirty, logs once, and recovers. */
    char unwritable[700];
    T(write_bytes(bad, "file") == 0);
    snprintf(unwritable, sizeof(unwritable), "%s/card.mcd", bad);
    memcard_rebind_paths(unwritable, NULL);
    T(memcard_write_sector(0, 101, sector) == 0);
    memcard_flush(0);
    memcard_flush(0);
    int dirty = 0;
    T(memcard_debug_info(0, NULL, NULL, NULL, &dirty) == 0 && dirty == 1);
    memcard_rebind_paths(card1, NULL);
    memcard_flush(0);
    T(memcard_debug_info(0, NULL, NULL, NULL, &dirty) == 0 && dirty == 0);
    T(file_byte(card1, 101 * MEMCARD_SECTOR_SIZE) == 0x33);
    T(file_byte(bak1, 100 * MEMCARD_SECTOR_SIZE) == 0xFF);

    /* A truncated card is set aside and replaced with a blank one, and the
     * blank card's first save keeps the earlier .bak. */
    char bak2[700];
    snprintf(bak2, sizeof(bak2), "%s.bak", card2);
    T(write_bytes(card2, "truncated") == 0);
    T(write_bytes(bak2, "previous") == 0);
    memcard_init(dir);
    T(memcard_is_present(1));
    T(file_size(card2) == MEMCARD_SIZE);
    T(file_byte(card1, 100 * MEMCARD_SECTOR_SIZE) == 0x33);
    T(memcard_write_sector(1, 100, sector) == 0);
    memcard_flush(1);
    T(file_byte(card2, 100 * MEMCARD_SECTOR_SIZE) == 0x33);
    T(file_size(bak2) == 8);
    return 0;
}
