# Crump

A class to interface with the Virginia State Corporation Commission's eFile quasi-Ajax API. Named for Beverly T. Crump, the first-ever commissioner of the SCC, from 1903–1907.

## Usage

### unique()
See if a name is taken, or is substantially similar to one that is taken. Returns `true` or `false`.

#### Example

```php
require 'class.Crump.inc.php';
$crump = new Crump;
$crump->name = 'McDonald’s';
var_dump($crump->unique());
```

Result is `bool(false)`.

### search()

Get a list of all records with a business name that contains the string in question. The string only needs to be one character long. By default, 25 results are returned, starting at result 0; these two can be adjusted to page through the results, or `$crump->num` can be set to an implausibly high value to have all results returned at once. Returns `true` or `false`, with results available within `$crump->results`.


#### Example

```php
require 'class.Crump.inc.php';
$crump = new Crump;
$crump->name = 'Coffee';
$crump->num = 3;
if ($crump->search() === TRUE)
{
	print_r($crump->results);
}
```

Result is:

```php
stdClass Object
(
    [count] => 878
    [list] => stdClass Object
        (
            [0] => stdClass Object
                (
                    [number] => 05864913
                    [name] => 2 SISTERS COFFEE CO.
                    [type] => Corporation
                    [status] => Purged
                )

            [1] => stdClass Object
                (
                    [number] => S0988248
                    [name] => 25TH ST. COFFEEHOUSE LLC
                    [type] => Limited Liability Company
                    [status] => Purged
                )

            [2] => stdClass Object
                (
                    [number] => S3703149
                    [name] => 3 SISTERS COFFEE LLC
                    [type] => Limited Liability Company
                    [status] => Canceled
                )

        )

)
```

## License

MIT.
