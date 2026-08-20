"""Schema de la base — 24 tablas de negocio + factura_seq.

Portado 1:1 de src-tauri/src/db.rs y facturas.rs (factura_seq).
Fechas: TEXT en formato dd/mm/YYYY (regla de AGENTS.md).
Montos/stock: DOUBLE PRECISION (equivalente a REAL/f64 de Rust).
"""
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()

TEXT_COLS = dict(collation=None)


def _id() -> Column:
    """PK autoincremental: INTEGER en SQLite (rowid alias), BIGSERIAL en Postgres."""
    return Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)

clientes = Table(
    "clientes", metadata,
    _id(),
    Column("nombre", String, nullable=False),
    Column("domicilio", String, nullable=False, server_default=""),
    Column("telefono", String, nullable=False, server_default=""),
    Column("dni", String, nullable=False, server_default=""),
    Column("provincia", String, nullable=False, server_default=""),
    Column("sucursal_recibir", String, nullable=False, server_default=""),
    Column("cp", String, nullable=False, server_default=""),
    Column("taller", String, nullable=False, server_default=""),
    Column("galeria", String, nullable=False, server_default=""),
)

facturas = Table(
    "facturas", metadata,
    _id(),
    Column("numero", String, nullable=False, unique=True),
    Column("fecha", String, nullable=False),
    Column("cliente_nombre", String, nullable=False, server_default=""),
    Column("domicilio", String, nullable=False, server_default=""),
    Column("telefono", String, nullable=False, server_default=""),
    Column("dni", String, nullable=False, server_default=""),
    Column("provincia", String, nullable=False, server_default=""),
    Column("sucursal_recibir", String, nullable=False, server_default=""),
    Column("cp", String, nullable=False, server_default=""),
    Column("taller", String, nullable=False, server_default=""),
    Column("galeria", String, nullable=False, server_default=""),
    Column("envio", Float, nullable=False, server_default="0"),
    Column("total", Float, nullable=False, server_default="0"),
    Column("tipo_entrega", String, nullable=False, server_default="'Retira'"),
    Column("fecha_estimada", String, nullable=False, server_default=""),
    Column("estado", String, nullable=False, server_default="'Pendiente'"),
    Column("notas", String, nullable=False, server_default=""),
    Column("fecha_despacho", String, nullable=False, server_default=""),
    Column("descuento_tipo", String, nullable=False, server_default="'percent'"),
    Column("descuento_valor", Float, nullable=False, server_default="0"),
    Column("entrega_estado", String, nullable=False, server_default="'No entregado'"),
)

factura_items = Table(
    "factura_items", metadata,
    _id(),
    Column("factura_id", BigInteger, ForeignKey("facturas.id", ondelete="CASCADE"), nullable=False),
    Column("cantidad", Float, nullable=False, server_default="1"),
    Column("detalle", String, nullable=False, server_default=""),
    Column("precio_unitario", Float, nullable=False, server_default="0"),
    Column("total", Float, nullable=False, server_default="0"),
    Column("producto_id", BigInteger, nullable=True),
)

productos = Table(
    "productos", metadata,
    _id(),
    Column("detalle", String, nullable=False),
    Column("precio_unitario", Float, nullable=False, server_default="0"),
    Column("stock_actual", Float, nullable=False, server_default="0"),
    Column("stock_minimo", Float, nullable=False, server_default="0"),
    Column("stock_reservado_factura", Float, nullable=False, server_default="0"),
    Column("stock_reservado_produccion", Float, nullable=False, server_default="0"),
    Column("imagen", String, nullable=False, server_default=""),
)

cuenta_corriente = Table(
    "cuenta_corriente", metadata,
    _id(),
    Column("cliente_id", BigInteger, ForeignKey("clientes.id", ondelete="CASCADE"), nullable=False),
    Column("fecha", String, nullable=False),
    Column("tipo", String, nullable=False),
    Column("referencia", String, nullable=False, server_default=""),
    Column("descripcion", String, nullable=False, server_default=""),
    Column("debe", Float, nullable=False, server_default="0"),
    Column("haber", Float, nullable=False, server_default="0"),
    Column("saldo", Float, nullable=False, server_default="0"),
)

movimientos_wasi = Table(
    "movimientos_wasi", metadata,
    _id(),
    Column("fecha", String, nullable=False),
    Column("tipo", String, nullable=False),
    Column("categoria", String, nullable=False, server_default=""),
    Column("concepto", String, nullable=False, server_default=""),
    Column("monto", Float, nullable=False, server_default="0"),
    Column("movimiento_gasto_id", BigInteger, nullable=True),
    Column("factura_id", BigInteger, nullable=True),
    Column("cuenta_corriente_id", BigInteger, nullable=True),
)

entidades_gastos = Table(
    "entidades_gastos", metadata,
    _id(),
    Column("tipo", String, nullable=False),
    Column("nombre", String, nullable=False),
    Column("telefono", String, nullable=False, server_default=""),
    Column("descripcion", String, nullable=False, server_default=""),
)

movimientos_gastos = Table(
    "movimientos_gastos", metadata,
    _id(),
    Column("entidad_id", BigInteger, ForeignKey("entidades_gastos.id", ondelete="CASCADE"), nullable=False),
    Column("fecha", String, nullable=False),
    Column("tipo_movimiento", String, nullable=False),
    Column("descripcion", String, nullable=False, server_default=""),
    Column("debe", Float, nullable=False, server_default="0"),
    Column("haber", Float, nullable=False, server_default="0"),
    Column("saldo", Float, nullable=False, server_default="0"),
    Column("fecha_vencimiento", String, nullable=False, server_default=""),
)

ordenes_produccion = Table(
    "ordenes_produccion", metadata,
    _id(),
    Column("fecha", String, nullable=False),
    Column("numero_factura", String, nullable=False),
    Column("cliente_nombre", String, nullable=False, server_default=""),
    Column("detalle", String, nullable=False),
    Column("cantidad_pedida", Float, nullable=False, server_default="0"),
    Column("stock_disponible", Float, nullable=False, server_default="0"),
    Column("cantidad_a_producir", Float, nullable=False, server_default="0"),
    Column("estado", String, nullable=False, server_default="'Pendiente'"),
    Column("notas", String, nullable=False, server_default=""),
)

empleados_config = Table(
    "empleados_config", metadata,
    _id(),
    Column("entidad_id", BigInteger, ForeignKey("entidades_gastos.id", ondelete="CASCADE"), nullable=False, unique=True),
    Column("sueldo_base", Float, nullable=False, server_default="0"),
    Column("modalidad", String, nullable=False, server_default="'Mensual'"),
    Column("multa_monto", Float, nullable=False, server_default="0"),
)

asistencia_empleados = Table(
    "asistencia_empleados", metadata,
    _id(),
    Column("entidad_id", BigInteger, ForeignKey("entidades_gastos.id", ondelete="CASCADE"), nullable=False),
    Column("fecha", String, nullable=False),
    Column("estado", String, nullable=False),
    Column("nota", String, nullable=False, server_default=""),
    Column("hora", String, nullable=False, server_default=""),
)

actividad_reciente = Table(
    "actividad_reciente", metadata,
    _id(),
    Column("fecha", String, nullable=False),
    Column("tipo", String, nullable=False),
    Column("descripcion", String, nullable=False),
    Column("referencia", String, nullable=False, server_default=""),
)

pagos_proveedores = Table(
    "pagos_proveedores", metadata,
    _id(),
    Column("entidad_gasto_id", BigInteger, ForeignKey("entidades_gastos.id", ondelete="SET NULL"), nullable=True),
    Column("proveedor", String, nullable=False),
    Column("fecha_vencimiento", String, nullable=False),
    Column("monto", Float, nullable=False, server_default="0"),
    Column("pagado", Integer, nullable=False, server_default="0"),
    Column("notas", String, nullable=False, server_default=""),
    Column("movimiento_gasto_id", BigInteger, nullable=True),
)

maquinas = Table(
    "maquinas", metadata,
    _id(),
    Column("nombre", String, nullable=False),
    Column("descripcion", String, nullable=False, server_default=""),
)

produccion_maquina = Table(
    "produccion_maquina", metadata,
    _id(),
    Column("maquina_id", BigInteger, ForeignKey("maquinas.id", ondelete="CASCADE"), nullable=False),
    Column("fecha", String, nullable=False),
    Column("cantidad", Float, nullable=False, server_default="0"),
    Column("unidad", String, nullable=False, server_default="'unidades'"),
)

notas_maquina = Table(
    "notas_maquina", metadata,
    _id(),
    Column("maquina_id", BigInteger, ForeignKey("maquinas.id", ondelete="CASCADE"), nullable=False),
    Column("nota", String, nullable=False),
    Column("fecha_hora", String, nullable=False, server_default=""),
)

cerrado_maquinas = Table(
    "cerrado_maquinas", metadata,
    _id(),
    Column("nombre", String, nullable=False),
    Column("descripcion", String, nullable=False, server_default=""),
)

cerrado_notas = Table(
    "cerrado_notas", metadata,
    _id(),
    Column("maquina_id", BigInteger, ForeignKey("cerrado_maquinas.id", ondelete="CASCADE"), nullable=False),
    Column("nota", String, nullable=False),
    Column("fecha_hora", String, nullable=False, server_default=""),
)

cerrado_medias = Table(
    "cerrado_medias", metadata,
    _id(),
    Column("maquina_id", BigInteger, ForeignKey("cerrado_maquinas.id", ondelete="CASCADE"), nullable=False),
    Column("fecha", String, nullable=False),
    Column("cantidad", Float, nullable=False, server_default="0"),
)

embolsado_empleados = Table(
    "embolsado_empleados", metadata,
    _id(),
    Column("nombre", String, nullable=False),
    Column("descripcion", String, nullable=False, server_default=""),
)

embolsado_notas = Table(
    "embolsado_notas", metadata,
    _id(),
    Column("empleado_id", BigInteger, ForeignKey("embolsado_empleados.id", ondelete="CASCADE"), nullable=False),
    Column("nota", String, nullable=False),
    Column("fecha_hora", String, nullable=False, server_default=""),
)

embolsado_docenas = Table(
    "embolsado_docenas", metadata,
    _id(),
    Column("maquina_id", BigInteger, ForeignKey("embolsado_empleados.id", ondelete="CASCADE"), nullable=False),
    Column("fecha", String, nullable=False),
    Column("docenas", Float, nullable=False, server_default="0"),
)

categorias_gasto = Table(
    "categorias_gasto", metadata,
    _id(),
    Column("nombre", String, nullable=False, unique=True),
)

stock_movements = Table(
    "stock_movements", metadata,
    _id(),
    Column("producto_id", BigInteger, ForeignKey("productos.id", ondelete="CASCADE"), nullable=False),
    Column("fecha_hora", String, nullable=False),
    Column("tipo", String, nullable=False),
    Column("referencia", String, nullable=False, server_default=""),
    Column("cantidad", Float, nullable=False),
    Column("stock_anterior", Float, nullable=False),
    Column("stock_nuevo", Float, nullable=False),
    Column("detalle", String, nullable=False, server_default=""),
)

factura_seq = Table(
    "factura_seq", metadata,
    _id(),
    Column("counter", BigInteger, nullable=False),
)

costos_medias = Table(
    "costos_medias", metadata,
    _id(),
    Column("nombre", String, nullable=False, unique=True),
    Column("docenas", Float, nullable=False, server_default="0"),
    Column("pares_por_docena", Float, nullable=False, server_default="0"),
    Column("peso_por_par_kg", Float, nullable=False, server_default="0"),
    Column("algodon_total", Float, nullable=False, server_default="0"),
    Column("lycra_base", Float, nullable=False, server_default="0"),
    Column("goma_base", Float, nullable=False, server_default="0"),
    Column("factor", Float, nullable=False, server_default="0"),
    Column("descuento_efectivo_pct", Float, nullable=False, server_default="0"),
    Column("mano_de_obra", Float, nullable=False, server_default="0"),
    Column("otros_accesorios", Float, nullable=False, server_default="0"),
    Column("escenarios_precios", Text, nullable=False, server_default="[]"),
)