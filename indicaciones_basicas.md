

## Objetivo del proyecto

Obtener las sanciones del BOE diariamente, que se pueda poner por día y que todas las noches se le actualice y le vaya a una base de datos.
Hay que intentar obtener el número de contacto y dirección del sancionado.

El modelo de datos que hay que extraer sería una cosa tal que así:

```python
class Sancionado:
    name: str
    timestamp: str
    identifier: str # CIF o NIE o DNI
    address: str
    phone: str
    email: str
    sanction_reason: str
    id_sanction: str
    matricula_coche: str
    plazo_notificacion: str

class Sancionados:
    lista_sancionados: list[Sancionados]

```

Esto se tiene que ejecutar automáticamente cada 12 horas para que siempre esté actualizado lo que se extrae del BOE.


## Necesitamos

* Un frontend para poder pedir ese informe del BOE y que el modelo que extraiga.
* Un sistema basado en structured outputs para extraer la información obtenida del BOE.
* Un sistema de scrapping del BOE para obtener los datos de los que extraer la info estructurada.
* sistema de notificaciones
* base de datos
* interfaz de usuarios
* testing y documentación
