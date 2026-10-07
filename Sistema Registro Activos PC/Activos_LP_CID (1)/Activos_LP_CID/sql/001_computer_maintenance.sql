-- Modulo de Mantenimiento: registro de mantenimientos realizados a cada computadora
CREATE TABLE IF NOT EXISTS computer_maintenance (
    id                  SERIAL PRIMARY KEY,
    computer_id         INTEGER NOT NULL REFERENCES computers(id),
    fecha_mantenimiento DATE NOT NULL DEFAULT CURRENT_DATE,
    tipo_mantenimiento  VARCHAR(20) NOT NULL
                        CHECK (tipo_mantenimiento IN ('PREVENTIVO', 'CORRECTIVO')),
    descripcion         TEXT NOT NULL,
    tecnico             VARCHAR(150),
    costo               NUMERIC(10, 2),
    usuario_registro    VARCHAR(100),
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_computer_maintenance_computer
    ON computer_maintenance (computer_id, fecha_mantenimiento DESC);
